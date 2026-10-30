"""Default QGIS styles stored in the GeoPackage (table layer_styles, loaded by QGIS automatically).

roads: only routing level 0 (the full network; levels 1-3 repeat its important roads),
rule-based by road class (byte +16 bits 0-3), minor classes only when zoomed in (8.6 million
segments would make the country view very slow), not routable segments (kind 5) dashed grey, and
street name labels when zoomed in. parcels: thin outlines.
"""

# class: (colour, width mm, max visible scale denominator; 0 = always)
CLASSES = {
    0: ("#c8000a", 0.9, 0),
    1: ("#e65a00", 0.7, 0),
    2: ("#f0a000", 0.6, 2_000_000),
    3: ("#00a03c", 0.45, 500_000),
    4: ("#1e64dc", 0.3, 150_000),
    5: ("#787878", 0.25, 80_000),
    6: ("#a0a0a0", 0.2, 50_000),
}


def _line_symbol(name, colour, width, dash=False):
    pen = "dash" if dash else "solid"
    return f"""
      <symbol name="{name}" type="line" alpha="1" force_rhr="0" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option name="line_color" type="QString" value="{colour}"/>
            <Option name="line_width" type="QString" value="{width}"/>
            <Option name="line_width_unit" type="QString" value="MM"/>
            <Option name="line_style" type="QString" value="{pen}"/>
            <Option name="capstyle" type="QString" value="round"/>
            <Option name="joinstyle" type="QString" value="round"/>
          </Option>
        </layer>
      </symbol>"""


def roads_qml():
    rules, symbols = [], []
    key = 0
    for cls, (colour, width, maxscale) in sorted(CLASSES.items(), reverse=True):
        scale = f' scalemaxdenom="{maxscale}" scalemindenom="1"' if maxscale else ""
        rules.append(f'<rule key="r{key}" symbol="{key}" label="class {cls}" filter="&quot;level&quot; = 0 AND &quot;kind&quot; != 5 AND &quot;class&quot; = {cls}"{scale}/>')
        symbols.append(_line_symbol(str(key), colour, width))
        key += 1
    rules.append(f'<rule key="r{key}" symbol="{key}" label="not routable" filter="&quot;level&quot; = 0 AND &quot;kind&quot; = 5" scalemaxdenom="30000" scalemindenom="1"/>')
    symbols.append(_line_symbol(str(key), "#b4b4b4", 0.2, dash=True))
    return f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34" styleCategories="AllStyleCategories" labelsEnabled="1">
  <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="1">
    <rules key="root">
      {"".join(rules)}
    </rules>
    <symbols>{"".join(symbols)}
    </symbols>
    <orderby>
      <orderByClause asc="0" nullsFirst="0">"class"</orderByClause>
    </orderby>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="name" fontSize="8" fontSizeUnit="Point" textColor="40,40,40,255"
                  fontFamily="Sans Serif" isExpression="0" namedStyle="Regular">
        <text-buffer bufferDraw="1" bufferSize="0.8" bufferSizeUnits="MM" bufferColor="255,255,255,255"/>
      </text-style>
      <placement placement="2" placementFlags="10" repeatDistance="120" repeatDistanceUnits="MM"
                 overrunDistance="0" maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25"/>
      <rendering scaleVisibility="1" scaleMin="1" scaleMax="25000" mergeLines="1"
                 obstacle="1" limitNumLabels="0" displayAll="0"/>
    </settings>
  </labeling>
  <layerGeometryType>1</layerGeometryType>
</qgis>
"""


def parcels_qml():
    return """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34" styleCategories="AllStyleCategories">
  <renderer-v2 type="singleSymbol">
    <symbols>
      <symbol name="0" type="fill" alpha="0.6" force_rhr="0" clip_to_extent="1">
        <layer class="SimpleFill" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option name="color" type="QString" value="0,0,0,0"/>
            <Option name="style" type="QString" value="no"/>
            <Option name="outline_color" type="QString" value="#7896c8"/>
            <Option name="outline_width" type="QString" value="0.15"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
"""


AREA_COLOURS = {1: "160,200,240", 3: "190,225,175", 5: "225,215,205", 6: "205,220,200", 8: "235,230,210"}


def _fill_symbol(name, rgb):
    return f"""
      <symbol name="{name}" type="fill" alpha="1" force_rhr="0" clip_to_extent="1">
        <layer class="SimpleFill" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option name="color" type="QString" value="{rgb},255"/>
            <Option name="style" type="QString" value="solid"/>
            <Option name="outline_style" type="QString" value="no"/>
          </Option>
        </layer>
      </symbol>"""


def areas_qml():
    """Areas by type; the fine level (0) up to 1:1 000 000, coarser levels further out."""
    rules, symbols, key = [], [], 0
    for level, lo, hi in ((0, 1, 1_000_000), (1, 1_000_000, 4_000_000), (2, 4_000_000, 8_000_000),
                          (3, 8_000_000, 20_000_000), (4, 20_000_000, 50_000_000), (5, 50_000_000, 0)):
        for typ, rgb in AREA_COLOURS.items():
            scale = f' scalemindenom="{lo}"' + (f' scalemaxdenom="{hi}"' if hi else "")
            rules.append(f'<rule key="a{key}" symbol="{key}" label="level {level} type {typ}" '
                         f'filter="&quot;level&quot; = {level} AND &quot;type&quot; = {typ}"{scale}/>')
            symbols.append(_fill_symbol(str(key), rgb))
            key += 1
    return f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34" styleCategories="AllStyleCategories" labelsEnabled="0">
  <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="1">
    <rules key="root">{"".join(rules)}</rules>
    <symbols>{"".join(symbols)}</symbols>
    <orderby><orderByClause asc="0" nullsFirst="0">"area_m2"</orderByClause></orderby>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
"""


def poi_qml():
    return """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34" styleCategories="AllStyleCategories" labelsEnabled="1" hasScaleBasedVisibilityFlag="1" maxScale="1" minScale="20000">
  <renderer-v2 type="singleSymbol">
    <symbols>
      <symbol name="0" type="marker" alpha="1" force_rhr="0" clip_to_extent="1">
        <layer class="SimpleMarker" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option name="name" type="QString" value="circle"/>
            <Option name="color" type="QString" value="200,40,40,255"/>
            <Option name="size" type="QString" value="1.8"/>
            <Option name="outline_color" type="QString" value="255,255,255,255"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="coalesce(&quot;name&quot;, &quot;brand&quot;)" isExpression="1" fontSize="7"
                  fontSizeUnit="Point" textColor="120,20,20,255" fontFamily="Sans Serif" namedStyle="Regular">
        <text-buffer bufferDraw="1" bufferSize="0.6" bufferSizeUnits="MM" bufferColor="255,255,255,255"/>
      </text-style>
      <placement placement="6" dist="1" distUnits="MM"/>
      <rendering scaleVisibility="1" scaleMin="1" scaleMax="8000" obstacle="1"/>
    </settings>
  </labeling>
  <layerGeometryType>0</layerGeometryType>
</qgis>
"""


def overview_qml():
    """The generalised roads only when zoomed out (the detailed roads take over closer in)."""
    return """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34" styleCategories="AllStyleCategories">
  <renderer-v2 type="RuleRenderer" symbollevels="0">
    <rules key="root">
      <rule key="o0" symbol="0" filter="&quot;level&quot; = 0 AND &quot;type&quot; >= 104" scalemindenom="2000000" scalemaxdenom="4000000"/>
      <rule key="o1" symbol="0" filter="&quot;level&quot; = 1" scalemindenom="4000000" scalemaxdenom="10000000"/>
      <rule key="o2" symbol="0" filter="&quot;level&quot; = 2" scalemindenom="10000000" scalemaxdenom="20000000"/>
      <rule key="o3" symbol="0" filter="&quot;level&quot; = 3" scalemindenom="20000000" scalemaxdenom="40000000"/>
      <rule key="o4" symbol="0" filter="&quot;level&quot; = 4" scalemindenom="40000000" scalemaxdenom="80000000"/>
      <rule key="o5" symbol="0" filter="&quot;level&quot; = 5" scalemindenom="80000000"/>
    </rules>
    <symbols>""" + _line_symbol("0", "#d04020", 0.4) + """
    </symbols>
  </renderer-v2>
  <layerGeometryType>1</layerGeometryType>
</qgis>
"""


def cities_qml():
    """City points with their names, from 1:500 000 in."""
    return """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34" styleCategories="AllStyleCategories" labelsEnabled="1" hasScaleBasedVisibilityFlag="1" maxScale="1" minScale="500000">
  <renderer-v2 type="singleSymbol">
    <symbols>
      <symbol name="0" type="marker" alpha="1" force_rhr="0" clip_to_extent="1">
        <layer class="SimpleMarker" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option name="name" type="QString" value="square"/>
            <Option name="color" type="QString" value="30,30,30,255"/>
            <Option name="size" type="QString" value="1.6"/>
            <Option name="outline_color" type="QString" value="255,255,255,255"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="name" fontSize="9" fontSizeUnit="Point" textColor="20,20,20,255"
                  fontFamily="Sans Serif" isExpression="0" namedStyle="Bold">
        <text-buffer bufferDraw="1" bufferSize="0.8" bufferSizeUnits="MM" bufferColor="255,255,255,255"/>
      </text-style>
      <placement placement="6" dist="1" distUnits="MM"/>
      <rendering scaleVisibility="1" scaleMin="1" scaleMax="500000" obstacle="1"/>
    </settings>
  </labeling>
  <layerGeometryType>0</layerGeometryType>
</qgis>
"""


def write_styles(db, layers):
    """layers: names present in the GeoPackage (styles only for the layers listed here)."""
    db.execute("""CREATE TABLE IF NOT EXISTS layer_styles (id INTEGER PRIMARY KEY AUTOINCREMENT,
        f_table_catalog TEXT, f_table_schema TEXT, f_table_name TEXT, f_geometry_column TEXT,
        styleName TEXT, styleQML TEXT, styleSLD TEXT, useAsDefault BOOLEAN, description TEXT,
        owner TEXT, ui TEXT, update_time DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    styles = {"roads": roads_qml(), "parcels": parcels_qml(), "areas": areas_qml(), "poi": poi_qml(),
              "overview_roads": overview_qml(), "cities": cities_qml()}
    for name, qml in styles.items():
        if name not in layers:
            continue
        db.execute("DELETE FROM layer_styles WHERE f_table_name = ?", (name,))
        db.execute("INSERT INTO layer_styles (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, "
                   "styleName, styleQML, styleSLD, useAsDefault, description, owner) "
                   "VALUES ('', '', ?, 'geom', ?, ?, '', 1, 'carindb navdb decoder', '')",
                   (name, f"{name} (navdb)", qml))
