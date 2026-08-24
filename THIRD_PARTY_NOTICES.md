# Third-Party Notices

Android Perf Lab is licensed under the Apache License 2.0. This file identifies
the principal third-party software used by the project. Each component remains
subject to its own copyright and license terms; Android Perf Lab does not
relicense third-party material.

## Source and runtime dependencies

| Component | Role | Upstream license | Upstream project |
| --- | --- | --- | --- |
| Perfetto Tools | External Android trace capture toolchain; selected files may be included in portable distributions | Apache-2.0 | <https://github.com/Gracker/perfetto-tools> |
| Google Perfetto / Perfetto Python API | Trace collection and processing | Apache-2.0 | <https://github.com/google/perfetto> |
| FastAPI | Local HTTP API | MIT | <https://github.com/fastapi/fastapi> |
| Uvicorn | Local ASGI server | BSD-3-Clause | <https://github.com/Kludex/uvicorn> |
| Protocol Buffers | Perfetto data support | BSD-3-Clause | <https://github.com/protocolbuffers/protobuf> |
| pywebview | Desktop WebView host | BSD-3-Clause | <https://github.com/r0x0r/pywebview> |

The exact direct and transitive Python dependency versions are recorded in
`uv.lock`. Dependencies downloaded during installation are not covered by the
Android Perf Lab license. Their license files and package metadata control.

## Build and packaged-distribution components

| Component | Role | License or applicable terms | Upstream project |
| --- | --- | --- | --- |
| PyInstaller | Windows packaging tool and bootloader | GPL-2.0-or-later with the upstream bootloader exception | <https://github.com/pyinstaller/pyinstaller> |
| Python | Runtime included by a PyInstaller build | PSF License | <https://www.python.org/psf/license/> |
| Gradle Wrapper | Reproducible Android build bootstrap | Apache-2.0 | <https://github.com/gradle/gradle> |
| Kotlin | Android overlay source and build toolchain | Apache-2.0 | <https://github.com/JetBrains/kotlin> |
| Android SDK Platform-Tools | `adb` and related runtime files in portable distributions | Licenses and notices contained in the accompanying `NOTICE.txt` | <https://developer.android.com/tools/releases/platform-tools> |
| Microsoft Edge WebView2 Runtime | External Windows prerequisite; not distributed by this repository | Microsoft license terms | <https://developer.microsoft.com/microsoft-edge/webview2/> |

Portable builds copy this project's `LICENSE`, `NOTICE`, and this file into the
release directory. They also preserve the Perfetto Tools license, the Android
Platform-Tools `NOTICE.txt`, and license files provided by installed Python
distributions. Do not remove those files when redistributing a build.

## Attribution and relationship disclaimer

Android Perf Lab is an independent project. It is not SmartPerfetto and is not
an official Google, Android, Perfetto, PerfDog, SoloX, Qualcomm, Microsoft, or
Gracker product. References to those names describe compatibility, data
sources, or comparison methodology only and do not imply sponsorship,
endorsement, or affiliation. All trademarks belong to their respective owners.

## Scope

This notice is provided for open-source compliance and attribution. It is not a
substitute for the complete license text supplied by each upstream component.
If the dependency set or packaged files change, update this notice and retain
all new upstream license and notice files before distributing the result.
