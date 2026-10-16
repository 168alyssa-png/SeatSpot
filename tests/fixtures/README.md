These small QR PNGs exercise the real browser decoder. They contain:

| File | QR contents |
| --- | --- |
| `table-b3.png` | `https://seatspot-zi36.vercel.app/?table=B3` |
| `table-b12.png` | `?table=b12` |
| `table-a2.png` | `https://seatspot-zi36.vercel.app/?table=A2` |
| `wrong-origin.png` | `https://example.com/?table=B3` |
| `unknown-table.png` | `https://seatspot-zi36.vercel.app/?table=B99` |
| `plain-text.png` | `B3` |
| `malformed.png` | `https://[broken/?table=B3` |

Generated with Python `qrcode==8.2`, error correction M, four-module border,
and one grayscale pixel per module. The PNG data uses filter zero and 8-bit
grayscale, so the tests can read it with Python's standard library and create
temporary Y4M camera input without Pillow, ffmpeg, or extra test dependencies.
Chromium supplies these frames through its real `getUserMedia` implementation;
the successful QR decoder is never mocked.
