// The actual track alignment for every line on the board: the way members
// of each route relation, with geometry. routes.ql fetches only the stop
// nodes, which is enough for station ORDER but says nothing about where the
// rails actually run - and a realistic map is exactly the shape of the
// rails. Relations are emitted too, so each way can be attributed to its
// line by membership.
[out:json][timeout:900];
(
  rel["type"="route"]["route"="subway"]["network"~"^(東京メトロ|都営地下鉄)$"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["route"~"^(tram|light_rail)$"]["name"~"荒川線"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["name"~"ゆりかもめ"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["name"~"りんかい線"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["name"~"山手線"](35.50,139.55,35.86,140.03);
  rel["type"="route"]["route"="train"]["name"~"新幹線"](35.50,139.55,35.86,140.03);
)->.r;
.r out body;
way(r.r);
out body geom;
