# QR decoder

`jsqr-1.4.0.js` is the unmodified browser distribution `dist/jsQR.js` from the npm package `jsqr@1.4.0` by the jsQR project: https://github.com/cozmo/jsQR.

It is distributed under Apache-2.0; see `jsqr-LICENSE.txt`. The package tarball was downloaded over verified HTTPS from `https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz` and checked against the registry's SHA-512 integrity metadata:

```text
sha512-dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A==
```

Decoder file SHA-256: `bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859`.

The scanner decodes video frames locally with this bundled JavaScript library, including on browsers without `BarcodeDetector`. It does not upload camera images or depend on a third-party CDN. Keep the `assets/` directory alongside `index.html` when deploying.
