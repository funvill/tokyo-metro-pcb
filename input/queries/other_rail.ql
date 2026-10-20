// Everything else that runs on rails inside the board's frame, so the
// question "what are we missing?" is answered from data rather than memory.
// Not fetched for the board - this is a scope check.
[out:json][timeout:300];
rel["type"="route"]["route"~"^(tram|light_rail|monorail|train)$"](35.50,139.55,35.86,140.03)->.r;
.r out tags;
