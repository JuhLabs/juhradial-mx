{
  description = "JuhRadial MX - Radial menu and device manager for Logitech MX Master (and any mouse) on Linux";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          gtkRuntimeLibs = with pkgs; [
            glib
            gtk4
            libadwaita
            gtk4-layer-shell
            (lib.getLib pango)
            gdk-pixbuf
            graphene
            gobject-introspection
            harfbuzz
          ];

          # Python environment with both PyQt6 (overlay) and PyGObject (settings)
          pythonEnv = pkgs.python3.withPackages (ps: with ps; [
            pyqt6
            pygobject3
            pycairo
          ]);

          # Rust daemon - handles evdev input and D-Bus signaling
          juhradiald = pkgs.rustPlatform.buildRustPackage {
            pname = "juhradiald";
            version = "0.4.5";

            # Include crates/mx-keypad beside daemon for the path dependency.
            src = ./.;
            cargoRoot = "daemon";
            buildAndTestSubdir = "daemon";

            cargoLock.lockFile = ./daemon/Cargo.lock;

            nativeBuildInputs = with pkgs; [ pkg-config ];
            buildInputs = with pkgs; [ dbus systemd ];

            meta = with pkgs.lib; {
              description = "JuhRadial MX daemon - HID++/evdev listener and D-Bus bridge";
              license = licenses.gpl3Only;
              platforms = platforms.linux;
            };
          };

        in
        {
          inherit juhradiald;

          default = pkgs.stdenv.mkDerivation {
            pname = "juhradial-mx";
            version = "0.4.5";
            src = ./.;

            nativeBuildInputs = with pkgs; [
              makeWrapper
              gobject-introspection
            ];

            buildInputs = gtkRuntimeLibs ++ (with pkgs; [
              qt6.qtbase
              qt6.qtsvg
              qt6.qtdeclarative
              qt6.qtwayland
            ]);

            dontBuild = true;
            dontWrapQtApps = true;
            dontWrapGApps = true;

            installPhase = ''
              runHook preInstall

              # Daemon binary
              install -Dm755 ${juhradiald}/bin/juhradiald $out/bin/juhradiald

              # Python overlay and settings scripts
              mkdir -p $out/share/juhradial
              cp overlay/*.py $out/share/juhradial/

              # Flow module
              cp -r overlay/flow $out/share/juhradial/

              # Locale files
              cp -r overlay/locales $out/share/juhradial/

              # Qt/QML settings app (tools/ excluded; GTK dashboard stays as fallback)
              mkdir -p $out/share/juhradial/settings-qt $out/share/juhradial/assets
              cp settings-qt/main.py $out/share/juhradial/settings-qt/
              cp -r settings-qt/bridge settings-qt/qml settings-qt/assets $out/share/juhradial/settings-qt/
              find $out/share/juhradial/settings-qt -type d -name __pycache__ -exec rm -rf {} +
              cp -r settings-qt/assets/wheels $out/share/juhradial/assets/

              # Assets - radial wheel images, device illustrations, AI icons
              mkdir -p $out/share/juhradial/assets/radial-wheels
              cp assets/radial-wheels/*.png $out/share/juhradial/assets/radial-wheels/
              if [ -d assets/devices ]; then
                mkdir -p $out/share/juhradial/assets/devices
                cp assets/devices/*.png assets/devices/*.svg $out/share/juhradial/assets/devices/ 2>/dev/null || true
              fi
              cp assets/ai-*.svg $out/share/juhradial/assets/ 2>/dev/null || true

              # Symlink so ../assets/ relative paths from overlay scripts resolve correctly
              # (overlay_actions.py, juhradial-overlay.py use os.path.dirname(__file__)/../assets/)
              ln -s $out/share/juhradial/assets $out/share/assets

              # Same for ../settings-qt/assets/ lookups (wheel skins in overlay_actions.py)
              ln -s $out/share/juhradial/settings-qt $out/share/settings-qt

              # App icon
              install -Dm644 assets/juhradial-mx.svg $out/share/icons/hicolor/scalable/apps/juhradial-mx.svg
              install -Dm644 assets/juhradial-mx.svg $out/share/juhradial/assets/juhradial-mx.svg

              # Desktop entries
              install -Dm644 packaging/juhradial-mx.desktop $out/share/applications/juhradial-mx.desktop
              install -Dm644 packaging/org.kde.juhradialmx.settings.desktop $out/share/applications/org.kde.juhradialmx.settings.desktop

              # Launcher scripts - write Nix-aware versions
              cat > $out/bin/juhradial-mx <<LAUNCHER
              #!/bin/bash
              # JuhRadial MX Launcher (Nix)
              pkill -f "juhradiald" 2>/dev/null
              pkill -f "juhradial-overlay" 2>/dev/null
              sleep 0.3
              ${pythonEnv}/bin/python3 $out/share/juhradial/juhradial-overlay.py &
              OVERLAY_PID=\$!
              $out/bin/juhradiald &
              DAEMON_PID=\$!
              echo "JuhRadial MX started"
              echo "  Overlay PID: \$OVERLAY_PID"
              echo "  Daemon PID: \$DAEMON_PID"
              wait \$DAEMON_PID
              LAUNCHER
              chmod 755 $out/bin/juhradial-mx

              cat > $out/bin/juhradial-settings <<LAUNCHER
              #!/bin/bash
              # JuhRadial MX Settings (Nix)
              # Prefer the Qt/QML settings app; fall back to the GTK dashboard
              if [ "\''${JUHRADIAL_SETTINGS:-}" != "gtk" ] && ${pythonEnv}/bin/python3 -c "import PyQt6.QtQml" 2>/dev/null; then
                  exec ${pythonEnv}/bin/python3 $out/share/juhradial/settings-qt/main.py "\$@"
              fi
              exec ${pythonEnv}/bin/python3 $out/share/juhradial/settings_dashboard.py "\$@"
              LAUNCHER
              chmod 755 $out/bin/juhradial-settings

              # systemd user service
              install -Dm644 packaging/systemd/juhradialmx-daemon.service $out/lib/systemd/user/juhradialmx-daemon.service
              substituteInPlace $out/lib/systemd/user/juhradialmx-daemon.service \
                --replace-fail "/usr/local/bin/juhradiald" "$out/bin/juhradiald"

              # udev rules (for NixOS module)
              install -Dm644 packaging/udev/99-juhradialmx.rules $out/etc/udev/rules.d/99-juhradialmx.rules

              runHook postInstall
            '';

            # Wrap launcher scripts with GTK/Qt environment variables
            postFixup = let
              typelibPath = pkgs.lib.makeSearchPath "lib/girepository-1.0" gtkRuntimeLibs;
              qtPluginPath = pkgs.lib.makeSearchPath "lib/qt-6/plugins" [ pkgs.qt6.qtbase pkgs.qt6.qtsvg pkgs.qt6.qtwayland ];
              qmlImportPath = pkgs.lib.makeSearchPath "lib/qt-6/qml" [ pkgs.qt6.qtdeclarative ];
            in ''
              wrapProgram $out/bin/juhradial-mx \
                --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath [ pkgs.gtk4-layer-shell ]}" \
                --set GI_TYPELIB_PATH "${typelibPath}" \
                --set QT_PLUGIN_PATH "${qtPluginPath}" \
                --prefix PYTHONPATH : "$out/share/juhradial"

              # QML2_IMPORT_PATH is the deprecated Qt 5 spelling; Qt 6 reads
              # QML_IMPORT_PATH but still honours the old name, so set both.
              wrapProgram $out/bin/juhradial-settings \
                --set GI_TYPELIB_PATH "${typelibPath}" \
                --set QT_PLUGIN_PATH "${qtPluginPath}" \
                --prefix QML_IMPORT_PATH : "${qmlImportPath}" \
                --prefix QML2_IMPORT_PATH : "${qmlImportPath}" \
                --prefix PYTHONPATH : "$out/share/juhradial"
            '';

            meta = with pkgs.lib; {
              description = "Radial menu and device manager for Logitech MX Master (and any mouse) on Linux";
              homepage = "https://github.com/JuhLabs/juhradial-mx";
              license = licenses.gpl3Only;
              platforms = platforms.linux;
              maintainers = [ ];
              mainProgram = "juhradial-mx";
            };
          };
        }
      );

      # NixOS module - enables systemd service + udev rules declaratively
      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.juhradial-mx;
        in
        {
          options.services.juhradial-mx = {
            enable = lib.mkEnableOption "JuhRadial MX radial menu for Logitech MX Master";

            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
              defaultText = lib.literalExpression "juhradial-mx.packages.\${pkgs.stdenv.hostPlatform.system}.default";
              description = "The JuhRadial MX package to use.";
            };
          };

          config = lib.mkIf cfg.enable {
            # Install the package system-wide
            environment.systemPackages = [ cfg.package ];

            # Register the packaged user unit and enable it declaratively.
            # Ordering lives in the unit; never pull in graphical-session.target.
            systemd.packages = [ cfg.package ];
            systemd.user.services.juhradialmx-daemon.wantedBy = [
              "graphical-session.target" "default.target"
            ];

            boot.kernelModules = [ "uinput" ];
            # Package registration avoids reading a built derivation at evaluation.
            services.udev.packages = [ cfg.package ];
            services.udev.extraRules = ''
              KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
            '';

            # Ensure 'input' group exists for device permissions
            users.groups.input = { };
          };
        };

      checks = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          package = self.packages.${system}.default;
          host = nixpkgs.lib.nixosSystem {
            inherit system;
            modules = [ self.nixosModules.default {
              services.juhradial-mx.enable = true;
              system.stateVersion = "24.11";
            } ];
          };
          cfg = host.config;
        in {
          inherit package;
          nixos-module =
            assert builtins.elem package cfg.systemd.packages;
            assert builtins.elem package cfg.services.udev.packages;
            assert builtins.elem "uinput" cfg.boot.kernelModules;
            assert cfg.users.groups ? input;
            assert builtins.elem "graphical-session.target"
              cfg.systemd.user.services.juhradialmx-daemon.wantedBy;
            pkgs.runCommand "juhradial-nixos-module" { } ''
              test -x ${package}/bin/juhradiald
              test -f ${package}/lib/systemd/user/juhradialmx-daemon.service
              grep -q 'SUBSYSTEM=="hidraw".*GROUP="input"' ${package}/etc/udev/rules.d/99-juhradialmx.rules
              grep -q 'KERNEL=="uinput".*GROUP="input".*MODE="0660"' ${pkgs.writeText "juhradial-extra-rules" cfg.services.udev.extraRules}
              touch $out
            '';
        });

      # Development shell for contributors
      devShells = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.mkShell {
            buildInputs = with pkgs; [
              rustc cargo pkg-config
              dbus systemd
              (python3.withPackages (ps: with ps; [ pyqt6 pygobject3 pycairo ]))
              gtk4 libadwaita gtk4-layer-shell graphene harfbuzz
              qt6.qtbase qt6.qtsvg qt6.qtdeclarative qt6.qtwayland
              gobject-introspection
            ];
          };
        }
      );
    };
}
