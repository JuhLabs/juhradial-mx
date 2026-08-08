use std::fs;
use std::os::unix::net::UnixStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use juhradiald::compositor::{trigger_kwin_cursor_script, KWinScripting};
use juhradiald::cursor::KWIN_CURSOR_SCRIPT;
use zbus::{connection::Builder, interface};

#[derive(Debug, Clone, PartialEq, Eq)]
enum Call {
    Load { script: String, plugin_name: String },
    Run,
    Unload { plugin_name: String },
}

#[derive(Clone)]
struct ScriptingMock {
    calls: Arc<Mutex<Vec<Call>>>,
    load_result: i32,
}

#[interface(name = "org.kde.kwin.Scripting")]
impl ScriptingMock {
    #[zbus(name = "loadScript")]
    fn load_script(&self, script_path: String, plugin_name: String) -> i32 {
        let script =
            fs::read_to_string(script_path).expect("KWin script temp file must stay alive");
        self.calls.lock().unwrap().push(Call::Load {
            script,
            plugin_name,
        });
        self.load_result
    }

    #[zbus(name = "unloadScript")]
    fn unload_script(&self, plugin_name: String) -> bool {
        self.calls
            .lock()
            .unwrap()
            .push(Call::Unload { plugin_name });
        true
    }
}

#[derive(Clone)]
struct ScriptMock {
    calls: Arc<Mutex<Vec<Call>>>,
    fail_run: bool,
}

#[interface(name = "org.kde.kwin.Script")]
impl ScriptMock {
    #[zbus(name = "run")]
    fn run(&self) -> zbus::fdo::Result<()> {
        self.calls.lock().unwrap().push(Call::Run);
        if self.fail_run {
            Err(zbus::fdo::Error::Failed(
                "simulated lost run reply".to_string(),
            ))
        } else {
            Ok(())
        }
    }
}

async fn kwin_peer(
    load_result: i32,
    fail_run: bool,
) -> (zbus::Connection, zbus::Connection, Arc<Mutex<Vec<Call>>>) {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let guid = zbus::Guid::generate();
    let (server_socket, client_socket) = UnixStream::pair().unwrap();

    let server = Builder::unix_stream(server_socket)
        .server(guid)
        .unwrap()
        .p2p()
        .name("org.kde.KWin")
        .unwrap()
        .serve_at(
            "/Scripting",
            ScriptingMock {
                calls: calls.clone(),
                load_result,
            },
        )
        .unwrap()
        .serve_at(
            "/Scripting/Script7",
            ScriptMock {
                calls: calls.clone(),
                fail_run,
            },
        )
        .unwrap()
        .build();
    let client = Builder::unix_stream(client_socket).p2p().build();
    let (server, client) = tokio::try_join!(server, client).unwrap();

    (server, client, calls)
}

#[tokio::test]
async fn cursor_script_uses_native_load_run_and_unload_calls() {
    let (_server, client, calls) = kwin_peer(7, false).await;
    let scripting = KWinScripting::new(client);
    let fallback_called = Arc::new(AtomicBool::new(false));
    let fallback_flag = fallback_called.clone();

    trigger_kwin_cursor_script(Some(&scripting), move || async move {
        fallback_flag.store(true, Ordering::SeqCst);
    })
    .await;

    assert!(
        !fallback_called.load(Ordering::SeqCst),
        "a confirmed run must not invoke the handler fallback"
    );
    let calls = calls.lock().unwrap();
    assert_eq!(calls.len(), 3);
    let plugin_name = match &calls[0] {
        Call::Load {
            script,
            plugin_name,
        } => {
            assert_eq!(script, KWIN_CURSOR_SCRIPT);
            assert!(plugin_name.starts_with("juhradial-cursor-"));
            plugin_name.clone()
        }
        call => panic!("expected loadScript first, got {call:?}"),
    };
    assert_eq!(calls[1], Call::Run);
    assert_eq!(calls[2], Call::Unload { plugin_name });
}

#[tokio::test]
async fn dispatched_run_error_suppresses_handler_fallback_and_still_cleans_up() {
    let (_server, client, calls) = kwin_peer(7, true).await;
    let scripting = KWinScripting::new(client);
    let fallback_called = Arc::new(AtomicBool::new(false));
    let fallback_flag = fallback_called.clone();

    trigger_kwin_cursor_script(Some(&scripting), move || async move {
        fallback_flag.store(true, Ordering::SeqCst);
    })
    .await;

    let calls = calls.lock().unwrap();
    assert_eq!(calls.len(), 3);
    assert_eq!(calls[1], Call::Run);
    assert!(matches!(calls[2], Call::Unload { .. }));
    assert!(
        !fallback_called.load(Ordering::SeqCst),
        "a run error is outcome-unknown after dispatch and must not double-open via fallback"
    );
}

#[tokio::test]
async fn rejected_load_preserves_pre_dispatch_handler_fallback() {
    let (_server, client, calls) = kwin_peer(-1, false).await;
    let scripting = KWinScripting::new(client);
    let fallback_called = Arc::new(AtomicBool::new(false));
    let fallback_flag = fallback_called.clone();

    trigger_kwin_cursor_script(Some(&scripting), move || async move {
        fallback_flag.store(true, Ordering::SeqCst);
    })
    .await;

    assert!(
        fallback_called.load(Ordering::SeqCst),
        "load rejection is definitely pre-dispatch and must invoke fallback"
    );
    let calls = calls.lock().unwrap();
    assert_eq!(calls.len(), 1);
    assert!(matches!(calls[0], Call::Load { .. }));
}
