"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                          LUMINA STUDIO v1.6.0                                 ║
║                    Multi-Material 3D Print Color System                       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Author: [MIN]                                                                ║
║  License: CC BY-NC-SA 4.0                                                     ║
╚═══════════════════════════════════════════════════════════════════════════════╝

System Tray Icon Module
"""

import os
import sys
import webbrowser
import pystray
from PIL import Image
import locale


class LuminaTray:
    def __init__(self, port=7860):
        self.port = port
        self.icon = None
        self.running = False
        self.language = self._get_system_language()

    def _get_system_language(self):
        """Detect system language and return language code."""
        try:
            lang, encoding = locale.getdefaultlocale()
            if lang:
                return lang.split('_')[0].lower()
            return 'en'
        except Exception:
            return 'en'
        
    def _get_text(self, key):
        """Get localized text based on system language."""
        texts = {
            'en': {
                'open_web_ui': 'Open Web UI',
                'open_github': 'Open GitHub',
                'exit': 'Exit'
            },
            'zh': {
                'open_web_ui': '打开WebUI',
                'open_github': '打开GitHub',
                'exit': '退出'
            }
        }
        
        # Return text in detected language, fallback to English
        return texts.get(self.language, texts['en']).get(key, texts['en'][key])

    def open_browser(self, icon=None, item=None):
        """Open web interface in default browser."""
        webbrowser.open(f"http://127.0.0.1:{self.port}")

    def open_github(self, icon=None, item=None):
        """Open GitHub repository in default browser."""
        webbrowser.open("https://github.com/MOVIBALE/Lumina-Layers")

    def exit_app(self, icon=None, item=None):
        """Shutdown the application completely."""
        print("Exiting application...")
        if self.icon:
            self.icon.stop()
        self.running = False
        os._exit(0)  # Force kill all threads (including Gradio)

    def setup_tray(self):
        """Configure tray icon and menu."""
        # Try to load icon, fallback to red square if missing
        import sys
        
        # Handle both dev and frozen modes for icon path
        if getattr(sys, 'frozen', False):
            # In frozen mode, check both exe directory and _MEIPASS
            icon_path = None
            # First try exe directory (where we copy it in the spec file)
            exe_dir_icon = os.path.join(os.path.dirname(sys.executable), "icon.ico")
            if os.path.exists(exe_dir_icon):
                icon_path = exe_dir_icon
            # Then try _MEIPASS (bundled resources)
            elif hasattr(sys, '_MEIPASS') and os.path.exists(os.path.join(sys._MEIPASS, "icon.ico")):
                icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        else:
            # Running as script
            icon_path = "icon.ico" if os.path.exists("icon.ico") else None

        try:
            if icon_path and os.path.exists(icon_path):
                image = Image.open(icon_path)
            else:
                raise FileNotFoundError("Icon not found")
                
            # On macOS, menu bar icons should be small (16x16 to 22x22)
            # Resize if needed for better display
            if sys.platform == "darwin":
                # macOS menu bar icons work best at 22x22 or smaller
                if image.size[0] > 22 or image.size[1] > 22:
                    image = image.resize((22, 22), Image.Resampling.LANCZOS)
            else:
                # Other platforms can use larger icons
                if image.size[0] > 64 or image.size[1] > 64:
                    image = image.resize((64, 64), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"⚠️ Warning: Failed to load icon from {icon_path}: {e}")
            # Create a simple fallback icon
            if sys.platform == "darwin":
                image = Image.new('RGB', (22, 22), color='red')
            else:
                image = Image.new('RGB', (64, 64), color='red')

        menu = pystray.Menu(
            pystray.MenuItem(self._get_text('open_web_ui'), self.open_browser, default=True),
            pystray.MenuItem(self._get_text('open_github'), self.open_github),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._get_text('exit'), self.exit_app)
        )

        self.icon = pystray.Icon(
            "LuminaStudio",
            image,
            "Lumina Studio v1.6.0",
            menu
        )

    def run(self):
        """Start the tray icon in a daemon thread."""
        self.setup_tray()
        self.running = True
        
        print(f"✅ System tray icon starting on {sys.platform}")
        try:
            self.icon.run()
        except Exception as e:
            print(f"⚠️ Warning: Failed to start system tray: {e}")
            self.running = False
