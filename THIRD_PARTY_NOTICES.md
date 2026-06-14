# Third-party notices & acknowledgments

## Bundled rendering library — vis-network

Second Brain bundles **vis-network** (and its data layer **vis-data**) so the interactive graph
viewer works fully offline (no CDN, no network access required). They are combined into a single
minified bundle, `second_brain/ui/vis-bundle.min.js`, built with esbuild, and inlined into the
single-file `view.html` at render time.

- **vis-network** — version 10.1.0 — License: Apache-2.0 OR MIT — https://github.com/visjs/vis-network
- **vis-data** — version 8.0.4 — License: Apache-2.0 OR MIT — https://github.com/visjs/vis-data

## Viewer design — adapted from Graphify (thank you!)

Second Brain's interactive viewer — the force-directed layout, community colouring, the search
box, the click-to-inspect **Node Info** panel with clickable neighbour navigation, the
per-community **show/hide legend** with "Select All", and the overall sidebar layout — is
**adapted from [Graphify](https://github.com/safishamsi/graphify)** by **Safi Shamsi**, used under
the **MIT License** (Copyright (c) 2026 Safi Shamsi). Graphify is the project whose graph viewer
inspired this one, and we're grateful for it. The adaptation maps Second Brain's own graph
(files, links, communities) into the same viewer and vendors the rendering library for offline use.

Graphify — https://github.com/safishamsi/graphify — MIT License, Copyright (c) 2026 Safi Shamsi.

The MIT and Apache-2.0 license texts are available at https://opensource.org/licenses/MIT and
https://www.apache.org/licenses/LICENSE-2.0 respectively.
