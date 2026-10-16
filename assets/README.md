# Build assets

| File | What it is |
|---|---|
| `app.ico` | Application icon for the Windows build (16–256 px), passed to PyInstaller by `build_exe.ps1` via `--icon`. |
| `translate.svg` | Source icon: the *translate* glyph from [Material Design Icons](https://github.com/google/material-design-icons) (Apache-2.0). |

The icon is a white glyph on a `#1e1f24` rounded square, matching `docs/images/social-preview.png`. To change it, edit `translate.svg`, render it on a 1024×1024 canvas and rebuild `app.ico`.
