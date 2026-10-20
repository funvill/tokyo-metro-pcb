// Station counts for the networks the board does not carry, so "what are we
// missing" is answered with numbers. Scope check only; not board data.
[out:json][timeout:300];
(
  rel["type"="route"]["route"~"^(tram|light_rail|monorail)$"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["route"="train"]["ref"~"^(JY|JK|JA|JB|JC)$"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["route"="train"]["name"~"りんかい線"](35.50,139.55,35.86,140.03);
)->.r;
.r out body;
node(r.r);
out body;
