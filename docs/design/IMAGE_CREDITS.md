# Image credits

Every photo on the public site comes from Wikimedia Commons. For each one, the licence, author and location were read
from the Commons file page, and then checked again by a second, independent reviewer
(`docs/overnight/phase_c_research.json`). Only images that passed both checks are used. They are self-hosted as WebP
with a JPEG fallback, at 800 px and 1600 px wide (never upscaled), by `tools/fetch_images.py`, which also writes
`src/agroshield_platform/web/static/img/credits.json`. The public Credits page (`/credits`) is generated from that file.

Rules followed: real photos of Kenya only, no public figures, no AI-generated people, no logos. Each image sits in a
fixed-ratio box with `object-fit: cover`, has alt text, lazy-loads below the fold and falls back to a plain panel if it
fails to load. Photos were resized and compressed; nothing else was changed. CC BY-SA copies are shared under the same licence.

## Used on the site

| Key | Commons file | Author | Licence | Place | Used on |
|---|---|---|---|---|---|
| `maize-mount-kenya` | [Maize on a Mount Kenya farm.jpg](https://commons.wikimedia.org/wiki/File:Maize_on_a_Mount_Kenya_farm.jpg) | CIAT | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) | Mount Kenya region, Kenya | Home hero |
| `maize-kuria` | [Maize Farming in Kuria East,Kenya.jpg](https://commons.wikimedia.org/wiki/File:Maize_Farming_in_Kuria_East,Kenya.jpg) | Elite Jac | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Kuria East, Kenya | Crops hero |
| `maize-siaya` | [Maize growing in local areas in Siaya county.jpg](https://commons.wikimedia.org/wiki/File:Maize_growing_in_local_areas_in_Siaya_county.jpg) | VickyOmondi | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Siaya County, Kenya | How it works |
| `farmer-shamba` | [Josephine Odiambo tested an improved maize variety in a corner of her shamba in Western Kenya (7603945196).jpg](https://commons.wikimedia.org/wiki/File:Josephine_Odiambo_tested_an_improved_maize_variety_in_a_corner_of_her_shamba_in_Western_Kenya_(7603945196).jpg) | USAID in Africa | [Public domain]() | Siranga, Western Kenya | Crops, replanting |
| `village-maize` | [CSIRO ScienceImage 4316 Equatorial rainforest is the backdrop to a village surrounded by a maize crop in Kenya Africa 1981.jpg](https://commons.wikimedia.org/wiki/File:CSIRO_ScienceImage_4316_Equatorial_rainforest_is_the_backdrop_to_a_village_surrounded_by_a_maize_crop_in_Kenya_Africa_1981.jpg) | Willem van Aken, CSIRO | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | Kenya (no more specific place given) | For insurers |
| `tea-kericho` | [Tea carpet plantation of Kericho highlands, in Kenya.jpg](https://commons.wikimedia.org/wiki/File:Tea_carpet_plantation_of_Kericho_highlands,_in_Kenya.jpg) | Carter.Maina | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Kericho highlands, Kenya | Home, highland farms |
| `kericho-farms` | [Kericho, Kenya (4201348827).jpg](https://commons.wikimedia.org/wiki/File:Kericho,_Kenya_(4201348827).jpg) | edskoch | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | Kericho County, Kenya | Learn hub |
| `camels-marsabit` | [Camels at Marsabit.jpg](https://commons.wikimedia.org/wiki/File:Camels_at_Marsabit.jpg) | Tish Madesh | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | Marsabit, Marsabit County, Kenya (page says 'Marsabit', category Marsabit National Park) | Livestock hero |
| `camels-north-horr` | [Camels in North Horr.jpg](https://commons.wikimedia.org/wiki/File:Camels_in_North_Horr.jpg) | Jens Klinzing | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) | Near North Horr, Marsabit County, Kenya (page says 'near North Horr, North Kenya') | Livestock |
| `camels-isiolo-road` | [Camels on road in Kenya.jpg](https://commons.wikimedia.org/wiki/File:Camels_on_road_in_Kenya.jpg) | Daniel Case | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | North of Isiolo, on the way to Samburu, Kenya (exact spot not stated) | Home, livestock card |
| `samburu-arid` | [Arid landscape with acacia tree, Samburu National Reserve, Kenya.jpg](https://commons.wikimedia.org/wiki/File:Arid_landscape_with_acacia_tree,_Samburu_National_Reserve,_Kenya.jpg) | Daniel Case | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Samburu National Reserve, Kenya | Livestock, dry rangeland |
| `savannah-after-rains` | [Savannah after the rains (42855065331).jpg](https://commons.wikimedia.org/wiki/File:Savannah_after_the_rains_(42855065331).jpg) | Kandukuru Nagarjun from Bangalore, India | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | Maasai Mara, Kenya | Livestock, green rangeland |
| `dry-river-kitui` | [Dry river, Kitui County, Kenya.jpg](https://commons.wikimedia.org/wiki/File:Dry_river,_Kitui_County,_Kenya.jpg) | John Nguru Kamau | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Kitui County, Kenya | Learn, basis risk |
| `chasing-rain-mara` | [Chasing the rain, Masai Mara.jpg](https://commons.wikimedia.org/wiki/File:Chasing_the_rain,_Masai_Mara.jpg) | Wajahat Mahmood | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) | Masai Mara, Narok County, Kenya | How it works, rainfall |
| `women-sorting` | [African Women Sorting their produce after harvest.jpg](https://commons.wikimedia.org/wiki/File:African_Women_Sorting_their_produce_after_harvest.jpg) | Kabai Ken | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Kenya (per categories; no specific place given) | For SACCOs |
| `rainbow-samburu` | [Rainbow over Samburu National Reserve landscape, Kenya.jpg](https://commons.wikimedia.org/wiki/File:Rainbow_over_Samburu_National_Reserve_landscape,_Kenya.jpg) | Daniel Case | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | Samburu National Reserve, Kenya | Request a demo |

## Checked but not used

Licence confirmed, kept as spares:

- [African women farmers in Kenya.jpg](https://commons.wikimedia.org/wiki/File:African_women_farmers_in_Kenya.jpg): Anthony mbuthia, CC BY-SA 4.0
- [Flood river full of erosion in Daraja Mbili Kisii County Kenya East Africa.jpg](https://commons.wikimedia.org/wiki/File:Flood_river_full_of_erosion_in_Daraja_Mbili_Kisii_County_Kenya_East_Africa.jpg): Osoro Osindi, CC BY-SA 4.0
- [Low volume, Nyamindi River, Kirinyaga County, Kenya.jpg](https://commons.wikimedia.org/wiki/File:Low_volume,_Nyamindi_River,_Kirinyaga_County,_Kenya.jpg): John Nguru Kamau, CC BY-SA 4.0
- [Kenya-Tealand-Near-Kericho-2012.JPG](https://commons.wikimedia.org/wiki/File:Kenya-Tealand-Near-Kericho-2012.JPG): Bjørn Christian Tørrissen, CC BY-SA 3.0
- [KER - Tea pickers working near Kericho, Kenya, 2012.jpg](https://commons.wikimedia.org/wiki/File:KER_-_Tea_pickers_working_near_Kericho,_Kenya,_2012.jpg): Josep M. Gracia, CC BY-SA 4.0
- [Chalbi Desert DSC08751.jpg](https://commons.wikimedia.org/wiki/File:Chalbi_Desert_DSC08751.jpg): Filiberto Strazzari, CC BY 2.0
- [Chalbi Desert DSC08753.jpg](https://commons.wikimedia.org/wiki/File:Chalbi_Desert_DSC08753.jpg): Filiberto Strazzari, CC BY 2.0
- [200812 kenya-9 (3213027119).jpg](https://commons.wikimedia.org/wiki/File:200812_kenya-9_(3213027119).jpg): Franco Pecchio from Milano, Italy, CC BY 2.0
- [01 camel.jpg](https://commons.wikimedia.org/wiki/File:01_camel.jpg): Jeffmugendi, CC BY-SA 4.0
- [US, Kenya veterinarians treat local animals during Justified Accord (8882983).jpg](https://commons.wikimedia.org/wiki/File:US,_Kenya_veterinarians_treat_local_animals_during_Justified_Accord_(8882983).jpg): U.S. Army photo by Staff Sgt. Josiah Jenkins, Public domain
- [Bare tree and boulders in arid landscape, Samburu National Reserve, Kenya.jpg](https://commons.wikimedia.org/wiki/File:Bare_tree_and_boulders_in_arid_landscape,_Samburu_National_Reserve,_Kenya.jpg): Daniel Case, CC BY-SA 4.0
- [Drought season in Lamu.jpg](https://commons.wikimedia.org/wiki/File:Drought_season_in_Lamu.jpg): HassanA2023, CC BY-SA 4.0
- [Maasai Mara landscape beneath clouds and sunbeams.jpg](https://commons.wikimedia.org/wiki/File:Maasai_Mara_landscape_beneath_clouds_and_sunbeams.jpg): Daniel Case, CC BY-SA 4.0

## Skipped

- Small-cropping-kenya (52428136678).jpg (for maize-highland): The API record says Public domain (PD USDA), and the author, URL and size match. But Commons also lists the file under 'United States Department of Agriculture images (review needed)', so the public domain status has not been reviewed yet. There is no licence URL. Under the default-to-false rule it is not confirmed until that review is done.

## Screenshots

`static/img/shots/` holds screenshots of the underwriter workspace on fictional demo data, made by
`tools/qa/shots.py`. They are AgroShield's own and need no licence; their captions say the data is fictional.
