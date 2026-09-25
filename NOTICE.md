# Attribution Notice

SROVA is a modified work derived from the hiresTI Music Player project.

- Upstream project: hiresTI Music Player
- Upstream repository: https://github.com/yelanxin/hiresTI
- Upstream licence: GNU General Public License version 3

SROVA retains portions of the upstream Python, Rust, GTK, audio, service, test,
icon and packaging code.

SROVA includes substantial modifications and additions for headless operation,
browser-based control, My Music, mounted Network Music, Internet Radio, TIDAL
and Qobuz provider support, remote control, Debian packaging, system-service
management, branding, queue behaviour and release validation.

Copyright in retained upstream portions remains with the original hiresTI
authors and contributors. Copyright in SROVA-specific modifications remains
with the respective SROVA contributors.

The inclusion of an upstream project name in attribution, retained source
identifiers or compatibility paths does not imply endorsement by the upstream
project.

This public snapshot corresponds to SROVA Version 2.0, Debian package
`2.0-1`.

It was curated from locked private release source commit:

`7e9d57aed0293aca85b2a707cf3843dde59bb2e5`

Private Git history is not imported into this public lineage.

The SROVA Remote Android application and SROVA Cast receiver/provisioning source
are separate projects and are not included in this repository. Player-side
SROVA Cast display assets used by the Linux player are included here.

## Spotify Soloist

SROVA Version 2.0 contains source code that can optionally manage Spotify's
official Soloist endpoint.

The Spotify Soloist executable and downloaded Soloist archives are not
redistributed in this public source snapshot. They are external runtime
artifacts obtained from Spotify when that integration is used.

Private Spotify API material, Soloist cache data and Soloist runtime state are
also excluded from public source custody.

Spotify/Soloist is an optional external convenience endpoint. It is not a
SROVA SOURCE 04 provider and is not represented as SROVA native
Bit-Perfect/exclusive playback.

## QBZ Qobuz reference

The Qobuz browser-service metadata extraction, catalog request/signing layer,
normalized catalog model mapping, CMAF delivery, parsing and cryptographic
implementation in `src/backend/qobuz.py`, `src/backend/qobuz_catalog.py` and
`src/backend/qobuz_cmaf.py` is adapted from the QBZ project at commit
`aa5690e4491507976b56a982025eb4b38ec8e064`:

- Repository: https://github.com/vicrodh/qbz
- Relevant upstream paths:
  `crates/qbz-qobuz/src/{auth,bundle,client,cmaf}.rs`,
  `crates/qbz-cmaf/src/{crypto,parser}.rs`, and
  `crates/qbz-models/src/types.rs`
- Licence: MIT

MIT License

Copyright (c) 2024 blitzkriegfc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The complete applicable GNU General Public License text for SROVA is provided
in `LICENSE`.
