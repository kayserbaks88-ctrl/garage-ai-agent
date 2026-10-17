# Staff Manager workplace photography

Downloaded and licence checked 17 October 2026. These are licensed photographs
of real people, used as illustrative workplace scenes. No product screenshots,
customer claims or testimonials are implied. No generated imagery is used.

Licence: https://www.pexels.com/license/

Pexels permits free website and marketing use and modification; attribution is
optional. People/brands must not be presented as endorsing a product. The page
explicitly identifies the scenes as stock photography and links photographer
credits and the licence. Do not resell or redistribute these as stock assets.

| Local basename | Photographer | Original photo |
| --- | --- | --- |
| mobile-clock-in | Mahsum Oğrak | https://www.pexels.com/photo/smiling-construction-worker-using-smartphone-outdoors-33477104/ |
| shift-planning | MART PRODUCTION | https://www.pexels.com/fr-fr/photo/gens-personnes-individus-travailler-7643756/ |
| workplace-team | Thirdman | https://www.pexels.com/photo/men-in-the-office-having-a-meeting-while-looking-at-camera-5684644/ |

Source download pattern: `https://images.pexels.com/photos/{photo-id}/pexels-photo-{photo-id}.jpeg`.
Photo IDs: 33477104, 7643756, 5684644 respectively.

Exports in `static/staff-manager/` use consistent 8:5 landscape crops, WebP at
320, 640, 960 and 1440 pixels, and progressive JPEG fallbacks at 960 pixels.
EXIF/location metadata is omitted. No phone screens or documents were fabricated.
All 15 exports total 816,876 bytes; the browser selects one variant per image.
The three 640-pixel WebP files total 89,936 bytes. Explicit image dimensions,
responsive sizes, lazy loading and async decoding reduce layout shifts and cost.
All page imagery is served locally; no stock-site image hotlinks are required.

The empty screenshot ZIP in `staff-manager-source/` is not used by the website.
Original downloads and processing scripts are local review artifacts under
`.release-validation/` and are not page assets.
