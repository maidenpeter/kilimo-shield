Information about CHIRPS Daily Precipitation

CHIRPS is fundamentally a pentadal and monthly precipitation product. CHIRPS is calculated at the pentadal and monthly time steps by blending station observations with CHIRP satellite-based precipitation estimates. The pentadal values are rescaled so that the pentads within a month sum to the monthly CHIRPS total.

Daily CHIRPS values are derived from the pentadal product. There is no separate daily station-blending step. Daily CHIRPS is therefore not an independent daily product: it combines the CHIRPS pentadal amount with the within-pentad timing from ERA5 or IMERG. We recommend using pentadal or monthly totals wherever the science allows.

Two versions of CHIRPS v3 daily precipitation are provided:

The identifiers 'rnl' and 'sat' represent the type of data used for temporal disaggregation: A reanalysis dataset and a satellite dataset.

	rnl uses daily precipitation from the ECMWF ERA5 reanalysis to temporally disaggregate each
	CHIRPS3 pentadal total among its constituent days. Available from 1981 to present.

	sat uses daily precipitation from NASA IMERG Late V07 to temporally disaggregate each
	CHIRPS3 pentadal total among its constituent days. Available from 1998 to present.

Both products begin with the same CHIRPS pentadal precipitation total.
They differ only in how that precipitation is distributed among days within the pentad.


Daily disaggregation:

In each case, the daily IMERG or ERA5 data are converted to ratios of the corresponding pentad total.
These daily ratios are multiplied by the CHIRPS3 pentad total to produce daily CHIRPS3 estimates.
When the ERA5 or IMERG pentad totals are zero, and the CHIRPS3 total is not, the CHIRPS3 total is divided evenly amongst the days. This can create artificial runs of consecutive wet days that reflect the method, not observed timing.

Therefore,
	i. rnl and sat sum to the same CHIRPS3 pentadal precipitation total
	ii. they may assign that precipitation differently among individual days
	For example, sat may place most of a pentad's rainfall on one day while rnl places more on a neighboring day.


Temporal convention:

ERA5 and IMERG are used according to their standard UTC calendar-day convention, without shifting. A CHIRPS3 daily value labelled with date D therefore uses the disaggregation information for approximately 00:00 UTC on D to 00:00 UTC on D+1.
However, this UTC convention applies to the daily disaggregation, not necessarily to all station observations contributing to the underlying CHIRPS3 pentadal total. CHIRPS3 incorporates station data from many sources, and for many stations the exact observation window is unknown. Some datasets use different reporting periods; for example, some GTS observations represent approximately 06:00 UTC to 06:00 UTC the following day.

The date on a daily CHIRPS3 value should therefore be interpreted as a consistent UTC calendar-day label used during disaggregation, rather than as a uniform 24-hour observation window for all contributing station data. This distinction is especially important for analyses that depend on the timing of individual rainfall events.

Shifting values to local time is not done automatically and does not resolve differences in station observation windows. Users comparing against station, sub-daily, or local-day data should account for this.

The GeoTIFF and NetCDF files use the same temporal convention (they contain the same data, packaged differently), and the convention is consistent throughout the record.


Spatial resolution:

ERA5 has a native spatial resolution of approximately 0.25°, while IMERGv7 has a native resolution of 0.1°. For production of the
0.05° CHIRPS3 daily products, both datasets are resampled to the CHIRPS3 0.05° grid using bilinear interpolation.
The 0.05° grid spacing of the daily products therefore should not be interpreted as indicating that the ERA5 or IMERG data used for temporal disaggregation contain information at 0.05° resolution.


Choosing between rnl and sat:

CHC does not give an official recommendation; the choice depends on the application.
	rnl uses ERA5 across the full record (1981 to present), which suits long, temporally consistent daily series.
	sat uses the finer-resolution IMERG input, which may retain more fine-scale variability in how rainfall is allocated among days.
We encourage users to compare rnl and sat to test how sensitive their results are to the disaggregation source. Example (Google Earth Engine): https://code.earthengine.google.com/5a671f5001a319cc4307cc6c9cb1b45a


Validation:

Agreement between rnl and ERA5, or between sat and IMERG, is expected by construction and is not independent validation. rnl and sat are also not fully independent of each other, because both are constrained by the same CHIRPS pentadal totals. Validation of daily CHIRPS should therefore focus on the timing and allocation of rainfall within each pentad, since the pentadal amount comes directly from CHIRPS.


Cautions for daily analyses:

Disaggregation can create artificial wet-day sequences, especially in the equal-split case described above. Onset dates, dry spells, wet-day counts, and daily extremes can differ substantially between rnl and sat. Daily extremes are pentadal amounts redistributed by ERA5 or IMERG, not independent station-based daily extremes. Pentadal metrics avoid much of this uncertainty and are preferred where the science allows. Where daily metrics are needed, state the disaggregation method used and test sensitivity with both rnl and sat.


Preliminary daily CHIRPS3:

IMERGv7 is available with sufficiently low latency to support the CHIRPS Preliminary production schedule. Therefore, the current preliminary daily CHIRPS v3 product uses the IMERG-based (sat) disaggregation. As with other CHIRPS Preliminary products, it should be replaced with CHIRPS Final once it is available.


Reference:

The CHIRPS v3 methodology is described in:
Funk, C., Peterson, P., Harrison, L., et al. (2026). The Climate Hazards Center Infrared Precipitation with Stations, Version 3. Scientific Data, 13, 718. https://doi.org/10.1038/s41597-026-07096-4



CHIRPS2 Daily:

CHIRPS v2 is being retired; its last month of operation will be December 2026. We encourage users to switch to CHIRPS v3. Information about CHIRPS2 daily data (which uses CFSv2 for temporal disaggregation) is available here: https://data.chc.ucsb.edu/products/CHIRPS-2.0/README-CHIRPS2-Daily.txt
