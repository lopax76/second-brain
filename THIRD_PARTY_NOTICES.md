# Third-party notices

Second Brain bundles the following third-party components so its graph viewer works fully
offline (no CDN, no network access required). They are combined into a single minified bundle,
`second_brain/ui/sigma-bundle.min.js`, built with esbuild. Each is redistributed under the
terms of the MIT License.

## sigma

- Version: 3.0.3
- Authors: Alexis Jacomy, Guillaume Plique (Ouestware) and contributors
- License: MIT
- Homepage: https://github.com/jacomyal/sigma.js

## graphology

- Version: 0.26.0
- Author: Guillaume Plique and contributors
- License: MIT
- Homepage: https://github.com/graphology/graphology

## graphology-layout-forceatlas2

- Version: 0.10.1
- Author: Guillaume Plique and contributors
- License: MIT
- Homepage: https://github.com/graphology/graphology-layout-forceatlas2

The bundle (`sigma-bundle.min.js`) exposes these on `window` (`Sigma`, `graphology`,
`forceAtlas2`) and is inlined into the single-file `view.html` at render time.
