"""py2app setup for JuhFlow Mac app."""

from setuptools import setup

APP = ['juhflow_app.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'JuhFlow',
        'CFBundleDisplayName': 'JuhFlow',
        'CFBundleIdentifier': 'com.juhlabs.juhflow',
        'CFBundleVersion': '0.1.0',
        'CFBundleShortVersionString': '0.1.0',
        'LSUIElement': True,  # Hide from Dock (menubar app)
        'NSAppleEventsUsageDescription': 'JuhFlow needs accessibility access for cursor control.',
    },
    'packages': ['cryptography'],
    'includes': ['rumps', 'Quartz', 'AppKit'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    install_requires=['rumps', 'cryptography', 'pyobjc-framework-Quartz'],
)
