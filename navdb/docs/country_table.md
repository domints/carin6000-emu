# Firmware country table

The country number of a map disc (table b +40, block 2 slot 2 settings; `libs/countries.py`)
indexes this table. It sits in the NAV_SW disc, `Mk2IC/{0109,0209}/RENAULT/app_sw/usw_load`
at 0x3ae1b (identical in both variants): 240 records of 6 bytes, `u8 index` (= number − 1) and a
5-byte NUL-padded car registration code, the code the menus show. Without a map the menus show
81 D.

The order is the alphabetical English country list of ISO 3166 from the late 1990s (with
"France, Metropolitan", "St. Helena" / "St. Pierre" sorted after "Sri Lanka", Zaire, Yugoslavia).
The table holds only the codes; the **names are inferred** from that order (the codes match
it everywhere), ? marks an uncertain one. Entries without a code show nothing in the menus.

Quirks of the firmware's codes: 27 BHI (international code BIH), 115 KS (KS), 208 TY (Tajikistan,
TJ), 222 UAG (UAE); 4 and 182 are both WS, 44 and 207 both RC. Serbia, Montenegro and Kosovo
have no number of their own (in 2000 they were Yugoslavia, 237 YU).

Used by the encoder (`libs/countries.py`): 171 PL; exyugoslavia 191 SLO, 53 HR, 27 BHI,
126 MK, 2 AL, 237 YU (Serbia), 235 and 236 without a code (Montenegro, Kosovo). The original disc:
33 BG, 53 HR, 56 CZ, 67 EW, 97 H, 117 LV, 123 LT, 171 PL, 176 RO, 190 SK, 191 SLO.

| No | Code | Country |
|---:|------|---------|
| 1 | AFG | Afghanistan |
| 2 | AL | Albania |
| 3 | DZ | Algeria |
| 4 | WS | American Samoa |
| 5 | AND | Andorra |
| 6 | ANG | Angola |
| 7 | | Anguilla |
| 8 | | Antarctica |
| 9 | | Antigua and Barbuda |
| 10 | RA | Argentina |
| 11 | | Armenia |
| 12 | | Aruba |
| 13 | AUS | Australia |
| 14 | A | Austria |
| 15 | AZ | Azerbaijan |
| 16 | BS | Bahamas |
| 17 | BRN | Bahrain |
| 18 | BD | Bangladesh |
| 19 | BDS | Barbados |
| 20 | BY | Belarus |
| 21 | B | Belgium |
| 22 | BH | Belize |
| 23 | DY | Benin |
| 24 | | Bermuda |
| 25 | | Bhutan |
| 26 | BOL | Bolivia |
| 27 | BHI | Bosnia and Herzegovina |
| 28 | RB | Botswana |
| 29 | | Bouvet Island |
| 30 | BR | Brazil |
| 31 | | British Indian Ocean Territory |
| 32 | BRU | Brunei |
| 33 | BG | Bulgaria |
| 34 | BF | Burkina Faso |
| 35 | BU | Burundi |
| 36 | K | Cambodia |
| 37 | | Cameroon |
| 38 | CDN | Canada |
| 39 | | Cape Verde |
| 40 | | Cayman Islands |
| 41 | RCA | Central African Republic |
| 42 | | Chad |
| 43 | RCH | Chile |
| 44 | RC | China |
| 45 | | Christmas Island |
| 46 | | Cocos (Keeling) Islands |
| 47 | CO | Colombia |
| 48 | | Comoros |
| 49 | RCB | Congo |
| 50 | | Cook Islands |
| 51 | CR | Costa Rica |
| 52 | CI | Côte d'Ivoire |
| 53 | HR | Croatia |
| 54 | C | Cuba |
| 55 | CY | Cyprus |
| 56 | CZ | Czech Republic |
| 57 | DK | Denmark |
| 58 | | Djibouti |
| 59 | WD | Dominica |
| 60 | DOM | Dominican Republic |
| 61 | | East Timor |
| 62 | EC | Ecuador |
| 63 | ET | Egypt |
| 64 | ES | El Salvador |
| 65 | | Equatorial Guinea |
| 66 | ER | Eritrea |
| 67 | EW | Estonia |
| 68 | ETH | Ethiopia |
| 69 | | Falkland Islands |
| 70 | FR | Faroe Islands |
| 71 | FJI | Fiji |
| 72 | FIN | Finland |
| 73 | F | France |
| 74 | | France, Metropolitan |
| 75 | | French Guiana |
| 76 | | French Polynesia |
| 77 | | French Southern Territories |
| 78 | | Gabon |
| 79 | WAG | Gambia |
| 80 | GE | Georgia |
| 81 | D | Germany |
| 82 | GH | Ghana |
| 83 | GBZ | Gibraltar |
| 84 | GR | Greece |
| 85 | | Greenland |
| 86 | WG | Grenada |
| 87 | | Guadeloupe |
| 88 | | Guam |
| 89 | GUA | Guatemala |
| 90 | | Guinea |
| 91 | | Guinea-Bissau |
| 92 | GUY | Guyana |
| 93 | RH | Haiti |
| 94 | | Heard and McDonald Islands |
| 95 | HN | Honduras |
| 96 | HK | Hong Kong |
| 97 | H | Hungary |
| 98 | IS | Iceland |
| 99 | IND | India |
| 100 | RI | Indonesia |
| 101 | IR | Iran |
| 102 | IRQ | Iraq |
| 103 | IRL | Ireland |
| 104 | IL | Israel |
| 105 | I | Italy |
| 106 | JA | Jamaica |
| 107 | J | Japan |
| 108 | JOR | Jordan |
| 109 | | Kazakhstan |
| 110 | EAK | Kenya |
| 111 | | Kiribati |
| 112 | | Korea, North |
| 113 | ROK | Korea, South |
| 114 | KWT | Kuwait |
| 115 | KS | Kyrgyzstan |
| 116 | LAO | Laos |
| 117 | LV | Latvia |
| 118 | RL | Lebanon |
| 119 | LS | Lesotho |
| 120 | LB | Liberia |
| 121 | | Libya |
| 122 | FL | Liechtenstein |
| 123 | LT | Lithuania |
| 124 | L | Luxembourg |
| 125 | | Macau |
| 126 | MK | Macedonia |
| 127 | RM | Madagascar |
| 128 | MW | Malawi |
| 129 | MAL | Malaysia |
| 130 | | Maldives |
| 131 | RMM | Mali |
| 132 | M | Malta |
| 133 | | Marshall Islands |
| 134 | | Martinique |
| 135 | RIM | Mauritania |
| 136 | MS | Mauritius |
| 137 | | Mayotte |
| 138 | MEX | Mexico |
| 139 | | Micronesia |
| 140 | MD | Moldova |
| 141 | MC | Monaco |
| 142 | | Mongolia |
| 143 | | Montserrat |
| 144 | MA | Morocco |
| 145 | MOC | Mozambique |
| 146 | MYA | Myanmar |
| 147 | NAM | Namibia |
| 148 | | Nauru |
| 149 | | Nepal |
| 150 | NL | Netherlands |
| 151 | NA | Netherlands Antilles |
| 152 | | New Caledonia |
| 153 | NZ | New Zealand |
| 154 | NIC | Nicaragua |
| 155 | RN | Niger |
| 156 | WAN | Nigeria |
| 157 | | Niue |
| 158 | | Norfolk Island |
| 159 | | Northern Mariana Islands |
| 160 | N | Norway |
| 161 | OM | Oman |
| 162 | PK | Pakistan |
| 163 | | Palau |
| 164 | | Palestine ? |
| 165 | PA | Panama |
| 166 | PNG | Papua New Guinea |
| 167 | PY | Paraguay |
| 168 | PE | Peru |
| 169 | RP | Philippines |
| 170 | | Pitcairn |
| 171 | PL | Poland |
| 172 | P | Portugal |
| 173 | | Puerto Rico |
| 174 | Q | Qatar |
| 175 | | Réunion |
| 176 | RO | Romania |
| 177 | RUS | Russia |
| 178 | RWA | Rwanda |
| 179 | | Saint Kitts and Nevis |
| 180 | WL | Saint Lucia |
| 181 | WV | Saint Vincent and the Grenadines |
| 182 | WS | Samoa |
| 183 | RSM | San Marino |
| 184 | | São Tomé and Príncipe |
| 185 | KSA | Saudi Arabia |
| 186 | SN | Senegal |
| 187 | SY | Seychelles |
| 188 | WAL | Sierra Leone |
| 189 | SGP | Singapore |
| 190 | SK | Slovakia |
| 191 | SLO | Slovenia |
| 192 | | Solomon Islands |
| 193 | SP | Somalia |
| 194 | ZA | South Africa |
| 195 | | South Georgia and the South Sandwich Islands |
| 196 | E | Spain |
| 197 | CL | Sri Lanka |
| 198 | | St. Helena |
| 199 | | St. Pierre and Miquelon |
| 200 | | Sudan |
| 201 | SME | Suriname |
| 202 | | Svalbard and Jan Mayen |
| 203 | SD | Swaziland |
| 204 | S | Sweden |
| 205 | CH | Switzerland |
| 206 | SYR | Syria |
| 207 | RC | Taiwan |
| 208 | TY | Tajikistan |
| 209 | EAT | Tanzania |
| 210 | THA | Thailand |
| 211 | TG | Togo |
| 212 | | Tokelau |
| 213 | | Tonga |
| 214 | TT | Trinidad and Tobago |
| 215 | TN | Tunisia |
| 216 | TR | Turkey |
| 217 | TM | Turkmenistan |
| 218 | | Turks and Caicos Islands |
| 219 | | Tuvalu |
| 220 | EAU | Uganda |
| 221 | UA | Ukraine |
| 222 | UAG | United Arab Emirates |
| 223 | GB | United Kingdom |
| 224 | USA | United States |
| 225 | | US Minor Outlying Islands |
| 226 | ROU | Uruguay |
| 227 | | Uzbekistan |
| 228 | | Vanuatu |
| 229 | V | Vatican City |
| 230 | YV | Venezuela |
| 231 | VN | Vietnam |
| 232 | | Virgin Islands (British) |
| 233 | | Virgin Islands (US) |
| 234 | | Wallis and Futuna |
| 235 | | Western Sahara |
| 236 | | Yemen |
| 237 | YU | Yugoslavia |
| 238 | ZRE | Zaire |
| 239 | Z | Zambia |
| 240 | ZW | Zimbabwe |
