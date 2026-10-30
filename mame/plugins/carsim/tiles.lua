-- license:BSD-3-Clause
-- OpenStreetMap tiles behind the car simulator window. Tiles are cached as <dir>/<z>/<x>/<y>.png
-- (CARIN_TILE_DIR, tools/carin.py sets <project>/temp/osm_tiles and trims the cache to 1 GB at
-- start). A tile older than 30 days is still shown and fetched again. Downloads run in the
-- background with curl, two at a time (OSM tile usage policy), each one marked by a .lock file
-- until it ends.
local lfs = require('lfs')

local tiles = { }

local URL = 'https://%s.tile.openstreetmap.org/%d/%d/%d.png'
local SUBDOMAINS = { 'a', 'b', 'c' }
local USER_AGENT = 'carin6000-emu car simulator (MAME plugin, personal testing)'
local MAX_AGE = 30 * 24 * 3600
local MAX_FETCHES = 2
local RETRY_AFTER = 60
local MAX_TEXTURES = 160
local TILE_SIZE = 256

local dir = os.getenv('CARIN_TILE_DIR') or 'osm_tiles'
local cache = { }          -- "z/x/y" -> { tex, state = 'ready' | 'queued' | 'fetching' | 'failed', ... }
local fetching = 0
local frame = 0
local subdomain = 0

local function mkdirs(path)
	local sofar = (path:sub(1, 1) == '/') and '' or nil
	for part in path:gmatch('[^/]+') do
		sofar = sofar and (sofar .. '/' .. part) or part
		lfs.mkdir(sofar)
	end
end

local function exists(path)
	return lfs.attributes(path, 'mode') == 'file'
end

local function load_texture(entry)
	local file = io.open(entry.path, 'rb')
	if not file then
		return false
	end
	local data = file:read('a')
	file:close()
	local ok, bitmap = pcall(emu.bitmap_argb32.load, data)
	if not ok or not bitmap then
		return false
	end
	if entry.tex then
		entry.tex:free()
	end
	entry.tex = manager.machine.render:texture_alloc(bitmap)
	entry.bitmap = bitmap
	return true
end

local function start_fetch(entry)
	mkdirs(entry.folder)
	local lock = entry.path .. '.lock'
	local file = io.open(lock, 'w')
	if not file then
		entry.state, entry.retry = 'failed', os.time() + RETRY_AFTER
		return
	end
	file:close()
	subdomain = subdomain % #SUBDOMAINS + 1
	local url = string.format(URL, SUBDOMAINS[subdomain], entry.z, entry.x, entry.y)
	local part = entry.path .. '.part'
	os.execute(string.format(
			"(curl -sf --max-time 20 -A '%s' -o '%s' '%s' && mv -f '%s' '%s'; rm -f '%s' '%s') >/dev/null 2>&1 &",
			USER_AGENT, part, url, part, entry.path, part, lock))
	entry.state, entry.started = 'fetching', os.time()
	fetching = fetching + 1
end

local function finish_fetch(entry)
	if exists(entry.path .. '.lock') and os.time() - entry.started < 60 then
		return
	end
	fetching = fetching - 1
	os.remove(entry.path .. '.lock')
	local mtime = lfs.attributes(entry.path, 'modification')
	if mtime and mtime >= entry.started - 1 and load_texture(entry) then
		entry.state = 'ready'
	elseif entry.tex then
		entry.state = 'ready'      -- keep the old one, try again later
		entry.refresh = os.time() + RETRY_AFTER
	else
		entry.state, entry.retry = 'failed', os.time() + RETRY_AFTER
	end
end

local function lookup(z, x, y)
	local key = z .. '/' .. x .. '/' .. y
	local entry = cache[key]
	if not entry then
		local folder = string.format('%s/%d/%d', dir, z, x)
		entry = { z = z, x = x, y = y, folder = folder, path = string.format('%s/%d.png', folder, y) }
		cache[key] = entry
		local mtime = lfs.attributes(entry.path, 'modification')
		if mtime and load_texture(entry) then
			entry.state = 'ready'
			if os.time() - mtime > MAX_AGE then
				entry.refresh = os.time()
			end
		else
			entry.state = 'queued'
		end
	end
	entry.used = frame
	return entry
end

local function evict()
	local count, oldest, oldest_key = 0, nil, nil
	for key, entry in pairs(cache) do
		count = count + 1
		if entry.state ~= 'fetching' and (not oldest or entry.used < oldest.used) then
			oldest, oldest_key = entry, key
		end
	end
	if count > MAX_TEXTURES and oldest and oldest.used < frame then
		if oldest.tex then
			oldest.tex:free()
		end
		cache[oldest_key] = nil
	end
end

-- Draws the tiles around (lat, lon) on the container of a screen width x height pixels, where one
-- screen pixel is mpp metres. Returns false while there is nothing to show yet.
function tiles.draw(container, width, height, lat, lon, mpp)
	frame = frame + 1
	local cos_lat = math.cos(math.rad(lat))
	-- the zoom whose tiles are shown at most 1:1 (crisp), at most 19
	local z = math.max(2, math.min(19, math.ceil(math.log(156543.03392 * cos_lat / mpp, 2))))
	local n = 2 ^ z
	local k = (156543.03392 * cos_lat / n) / mpp     -- screen pixels per tile pixel
	local cx = (lon + 180) / 360 * n * TILE_SIZE
	local sin_lat = math.sin(math.rad(lat))
	local cy = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * n * TILE_SIZE
	local half_w, half_h = width / 2 / k, height / 2 / k
	local x0, x1 = math.floor((cx - half_w) / TILE_SIZE), math.floor((cx + half_w) / TILE_SIZE)
	local y0, y1 = math.max(0, math.floor((cy - half_h) / TILE_SIZE)), math.min(n - 1, math.floor((cy + half_h) / TILE_SIZE))
	local shown = false

	local wanted = { }
	for ty = y0, y1 do
		for tx = x0, x1 do
			local entry = lookup(z, tx % n, ty)
			if entry.tex then
				local sx = (width / 2 + (tx * TILE_SIZE - cx) * k) / width
				local sy = (height / 2 + (ty * TILE_SIZE - cy) * k) / height
				container:draw_quad(entry.tex, sx, sy, sx + TILE_SIZE * k / width, sy + TILE_SIZE * k / height)
				shown = true
			end
			if entry.state == 'queued' or (entry.state == 'failed' and os.time() >= entry.retry)
					or (entry.state == 'ready' and entry.refresh and os.time() >= entry.refresh) then
				table.insert(wanted, entry)
			end
		end
	end

	-- finished downloads, then new ones for what is on screen now
	for _, entry in pairs(cache) do
		if entry.state == 'fetching' then
			finish_fetch(entry)
		end
	end
	for _, entry in ipairs(wanted) do
		if fetching >= MAX_FETCHES then
			break
		end
		entry.refresh = nil
		start_fetch(entry)
	end
	evict()
	return shown, fetching
end

-- Forget all textures (the machine stops).
function tiles.reset()
	for _, entry in pairs(cache) do
		if entry.tex then
			entry.tex:free()
		end
	end
	cache = { }
	fetching = 0
end

return tiles
