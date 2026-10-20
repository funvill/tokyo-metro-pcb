// The Shinkansen lines through Tokyo. Only three of their stations fall
// inside the board's frame - Tokyo, Ueno and Shinagawa - and all three are
// already LEDs, so the line costs nothing but silkscreen.
[out:json][timeout:300];
rel["type"="route"]["route"="train"]["name"~"新幹線"](35.50,139.55,35.86,140.03)->.r;
.r out body;
node(r.r);
out body;
