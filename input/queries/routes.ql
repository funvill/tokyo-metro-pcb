// Route relations for both subway operators, with their stop members in
// running order — this is where the per-line station order comes from.
// Toei's through-services onto Keisei/Keikyu are tagged
// network="京成;都営地下鉄" and are excluded by anchoring the match.
// The query must be sent from this file, not inline: Git Bash mangles the
// Japanese tag values on the way to curl, and Overpass then rejects the
// regular expression.
[out:json][timeout:300];
rel["type"="route"]["route"="subway"]["network"~"^(東京メトロ|都営地下鉄)$"](35.50,139.55,35.86,140.03)->.r;
.r out body;
node(r.r);
out body;
