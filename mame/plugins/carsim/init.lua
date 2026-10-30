-- license:BSD-3-Clause
-- CARiN car simulator window. The CARiN driver (philips/carin.cpp, car_sim_tick) simulates the car
-- behind the slave's dead reckoning and GPS; this plugin draws it on the driver's "carsim" screen
-- (view "Car simulator") and adds a menu (Plugin Options -> Car simulator) to move it.
-- It talks to the driver through outputs of the root device:
--   car_view0-7  0 latitude, 1 longitude (1e-7 degree), 2 heading (0.01 degree), 3 speed (cm/s),
--                4 odometer (m), 5 bit 0 GPS fix, bit 1 dp position service running, 6 last command done
--   car_cmd0-3   0 sequence number, 1 command, 2 3 arguments (see carin_state::car_sim_command)
local exports = {
	name = 'carsim',
	version = '0.1',
	description = 'CARiN car simulator window',
	license = 'BSD-3-Clause',
	author = { name = 'carin6000-emu' } }

local carsim = exports

local CMD_MOVE, CMD_HEADING, CMD_SPEED, CMD_GPS = 1, 2, 3, 4
local EARTH_RADIUS = 6378137.0
local SCALES = { 50, 100, 200, 500, 1000, 2000, 5000, 10000 }   -- metres from the centre to the top edge
local TRAIL_MAX = 3000

local stop_subscription

function carsim.startplugin()
	local tiles = require('carsim/tiles')
	local show_tiles = os.getenv('CARIN_TILES') ~= '0'
	local view, cmd, screen             -- output proxies and the screen; nil until found
	local car                           -- last decoded m_car_view
	local pending = { }                 -- commands not sent yet, by command number
	local sent                          -- sequence number of the last command sent
	local trail = { }                   -- { lat, lon } points, false = a jump
	local zoom = 3
	local coords = ''                   -- the coordinates typed in the menu
	local started = false               -- CARIN_CAR_AT applied

	-- "52.2297, 21.0122", "52.2297 21.0122", "52.2297N 21.0122E", "-33.86 151.21"
	local function parse(text)
		local values = { }
		for number, hemisphere in text:upper():gmatch('([-+]?%d+%.?%d*)%s*([NSEW]?)') do
			local value = tonumber(number)
			if hemisphere == 'S' or hemisphere == 'W' then
				value = -math.abs(value)
			end
			table.insert(values, value)
		end
		if #values ~= 2 or math.abs(values[1]) > 89 or math.abs(values[2]) > 180 then
			return nil
		end
		return values[1], values[2]
	end

	local function attach()
		if view then
			return true
		end
		local root = manager.machine.devices[':']
		screen = manager.machine.screens[':carsim']
		if not root or not screen or not root:output('car_view0'):exists() then
			return false
		end
		view, cmd = { }, { }
		for i = 0, 7 do
			view[i] = root:output('car_view' .. i)
		end
		for i = 0, 3 do
			cmd[i] = root:output('car_cmd' .. i)
		end
		sent = cmd[0]:get()
		-- tools/carin.py gui --car-at LAT,LON
		local start = os.getenv('CARIN_CAR_AT')
		if start and not started then
			started = true
			local lat, lon = parse(start)
			if lat then
				pending[CMD_MOVE] = { math.floor(lat * 1e7 + 0.5), math.floor(lon * 1e7 + 0.5) }
			else
				emu.print_error('carsim: CARIN_CAR_AT is not "lat,lon": ' .. start)
			end
		end
		return true
	end

	local function read_car()
		local v = { }
		for i = 0, 6 do
			v[i] = view[i]:get()
		end
		return {
			lat = v[0] * 1e-7, lon = v[1] * 1e-7, heading = v[2] / 100, speed = v[3] / 100,
			odometer = v[4], fix = (v[5] & 1) ~= 0, dp = (v[5] & 2) ~= 0, done = v[6] }
	end

	-- One command per driver tick: the driver carries it out and reports its sequence number.
	local function send_pending()
		if car.done ~= sent then
			return
		end
		for op = CMD_MOVE, CMD_GPS do
			local args = pending[op]
			if args then
				pending[op] = nil
				cmd[1]:set(op)
				cmd[2]:set(args[1] or 0)
				cmd[3]:set(args[2] or 0)
				sent = (sent + 1) & 0x7fffffff
				cmd[0]:set(sent)
				return
			end
		end
	end

	-- metres north and east of the car
	local function offset(lat, lon)
		local north = math.rad(lat - car.lat) * EARTH_RADIUS
		local east = math.rad(lon - car.lon) * EARTH_RADIUS * math.cos(math.rad(car.lat))
		return north, east
	end

	local function track()
		local last = trail[#trail]
		if last then
			local north, east = offset(last[1], last[2])
			local distance = math.sqrt(north * north + east * east)
			if distance < 3 then
				return
			end
			if distance > 2000 then
				table.insert(trail, false)
			end
		end
		table.insert(trail, { car.lat, car.lon })
		while #trail > TRAIL_MAX do
			table.remove(trail, 1)
		end
	end

	local function draw()
		local container = screen.container
		local scale = SCALES[zoom]
		local aspect = screen.height / screen.width
		local function point(north, east)
			return 0.5 + east / scale * 0.5 * aspect, 0.5 - north / scale * 0.5
		end
		local function inside(x, y)
			return x >= 0 and x <= 1 and y >= 0 and y <= 1
		end
		local function line(x1, y1, x2, y2, color)
			if inside(x1, y1) and inside(x2, y2) then
				container:draw_line(x1, y1, x2, y2, color)
			end
		end

		-- OpenStreetMap tiles; a grid fixed to the ground while there are none
		local mapped, loading = false, 0
		if show_tiles then
			mapped, loading = tiles.draw(container, screen.width, screen.height, car.lat, car.lon, scale / (screen.height / 2))
		end
		local step = scale / 4
		local magnitude = 10 ^ math.floor(math.log(step, 10))
		step = (step / magnitude >= 5) and 5 * magnitude or (step / magnitude >= 2) and 2 * magnitude or magnitude
		if not mapped then
			local car_north = math.rad(car.lat) * EARTH_RADIUS
			local car_east = math.rad(car.lon) * EARTH_RADIUS * math.cos(math.rad(car.lat))
			local reach = scale / aspect
			for k = math.ceil((car_north - scale) / step), math.floor((car_north + scale) / step) do
				local _, y = point(k * step - car_north, 0)
				line(0, y, 1, y, 0xff2a3038)
			end
			for k = math.ceil((car_east - reach) / step), math.floor((car_east + reach) / step) do
				local x = point(0, k * step - car_east)
				line(x, 0, x, 1, 0xff2a3038)
			end
		end

		-- where the car has been
		local previous
		for _, p in ipairs(trail) do
			if p then
				local x, y = point(offset(p[1], p[2]))
				if previous then
					line(previous[1], previous[2], x, y, 0xffe0a020)
				end
				previous = { x, y }
			else
				previous = nil
			end
		end

		-- the car: an arrow pointing where it heads
		local h = math.rad(car.heading)
		local function arrow(angle, length)
			return 0.5 + math.sin(h + angle) * length / screen.width, 0.5 - math.cos(h + angle) * length / screen.height
		end
		local tx, ty = arrow(0, 16)
		local lx, ly = arrow(math.rad(140), 11)
		local rx, ry = arrow(math.rad(-140), 11)
		local bx, by = arrow(math.pi, 4)
		local color = car.fix and 0xff00a040 or 0xffe02020
		line(tx, ty, lx, ly, color)
		line(lx, ly, bx, by, color)
		line(bx, by, rx, ry, color)
		line(rx, ry, tx, ty, color)

		-- scale bar
		local x0 = 0.03
		local x1 = point(0, step)
		x1 = x0 + (x1 - 0.5)
		local ink = mapped and 0xff202020 or 0xffd0d0d0
		line(x0, 0.93, x1, 0.93, ink)
		line(x0, 0.92, x0, 0.94, ink)
		line(x1, 0.92, x1, 0.94, ink)
		local label = (step >= 1000) and string.format('%g km', step / 1000) or string.format('%g m', step)
		container:draw_text(x1 + 0.01, 0.905, label, ink)
		if show_tiles then
			local credit = '\xc2\xa9 OpenStreetMap contributors' .. ((loading > 0) and '  (loading tiles)' or '')
			container:draw_text('right', 0.95, credit, 0xff202020, 0xc0ffffff)
		end

		local info = string.format(
				'%.7f %s  %.7f %s\nSpeed %.0f km/h   heading %.0f\xc2\xb0\nOdometer %.2f km\nGPS %s   dp %s',
				math.abs(car.lat), (car.lat < 0) and 'S' or 'N', math.abs(car.lon), (car.lon < 0) and 'W' or 'E',
				car.speed * 3.6, car.heading, car.odometer / 1000,
				car.fix and 'fix' or 'no fix', car.dp and 'running' or 'waiting')
		container:draw_text(0.02, 0.02, info, 0xffe8e8e8, 0xc0101418)
		container:draw_text('right', 0.02, 'W/S speed   A/D steer   Z stop\nTab: Plugin Options > Car simulator', 0xffc0c8d0, 0xc0101418)
	end

	local function frame_done()
		if not attach() then
			return
		end
		car = read_car()
		send_pending()
		track()
		if screen then
			draw()
		end
	end

	local item_coords, item_go, item_speed, item_heading, item_gps, item_zoom, item_tiles, item_clear

	local function wanted(op, current)
		return pending[op] and pending[op][1] or current
	end

	local function menu_populate()
		local result = { }
		table.insert(result, { 'Car simulator', '', 'off' })
		if not attach() then
			table.insert(result, { 'Not a CARiN system', '', 'off' })
			return result
		end
		car = read_car()
		table.insert(result, { 'Car at', string.format('%.6f, %.6f', car.lat, car.lon), 'off' })
		table.insert(result, { '---', '', '' })
		table.insert(result, { 'Coordinates (type)', (#coords > 0) and coords or 'lat, lon', '' })
		item_coords = #result
		table.insert(result, { 'Move the car there', '', '' })
		item_go = #result
		table.insert(result, { '---', '', '' })
		table.insert(result, { 'Speed', string.format('%.0f km/h', wanted(CMD_SPEED, car.speed * 100) * 0.036), 'lr' })
		item_speed = #result
		table.insert(result, { 'Heading', string.format('%.0f\xc2\xb0', wanted(CMD_HEADING, car.heading * 100) / 100), 'lr' })
		item_heading = #result
		table.insert(result, { 'GPS antenna', (wanted(CMD_GPS, car.fix and 1 or 0) ~= 0) and 'free' or 'covered', 'lr' })
		item_gps = #result
		table.insert(result, { 'Zoom', string.format('%g m', SCALES[zoom]), ((zoom > 1) and 'l' or '') .. ((zoom < #SCALES) and 'r' or '') })
		item_zoom = #result
		table.insert(result, { 'Map tiles (OpenStreetMap)', show_tiles and 'on' or 'off', show_tiles and 'l' or 'r' })
		item_tiles = #result
		table.insert(result, { 'Clear the trail', '', '' })
		item_clear = #result
		return result
	end

	local function menu_callback(index, event)
		if not attach() then
			return false
		end
		car = read_car()
		local step = (event == 'left') and -1 or (event == 'right') and 1 or 0
		if index == item_coords then
			local char = tonumber(event)
			if char then
				if char == 8 or char == 0x7f then
					coords = coords:sub(1, -2)
				elseif char >= 0x20 and char < 0x7f then
					coords = coords .. string.char(char)
				end
				return true
			elseif event == 'clear' then
				coords = ''
				return true
			elseif event == 'select' then
				index = item_go
			end
		end
		if index == item_go and event == 'select' then
			local lat, lon = parse(coords)
			if not lat then
				manager.machine:popmessage('Type the coordinates as: 52.2297, 21.0122')
				return false
			end
			pending[CMD_MOVE] = { math.floor(lat * 1e7 + 0.5), math.floor(lon * 1e7 + 0.5) }
			trail = { }
			manager.machine:popmessage(string.format('Car moved to %.6f, %.6f', lat, lon))
			return true
		elseif index == item_speed and step ~= 0 then
			local speed = wanted(CMD_SPEED, math.floor(car.speed * 100 + 0.5)) * 0.036
			speed = math.max(-18, math.min(180, (math.floor(speed / 10 + 0.5) + step) * 10))
			pending[CMD_SPEED] = { math.floor(speed / 0.036 + 0.5) }
			return true
		elseif index == item_heading and step ~= 0 then
			local heading = wanted(CMD_HEADING, math.floor(car.heading * 100 + 0.5)) / 100
			heading = ((math.floor(heading / 15 + 0.5) + step) * 15) % 360
			pending[CMD_HEADING] = { math.floor(heading * 100 + 0.5) }
			return true
		elseif index == item_gps and (step ~= 0 or event == 'select') then
			pending[CMD_GPS] = { (wanted(CMD_GPS, car.fix and 1 or 0) ~= 0) and 0 or 1 }
			return true
		elseif index == item_zoom and step ~= 0 then
			zoom = math.max(1, math.min(#SCALES, zoom + step))
			return true
		elseif index == item_tiles and (step ~= 0 or event == 'select') then
			show_tiles = not show_tiles
			return true
		elseif index == item_clear and event == 'select' then
			trail = { }
			return true
		end
		return false
	end

	stop_subscription = emu.add_machine_stop_notifier(function ()
		view, cmd, screen = nil, nil, nil
		tiles.reset()
	end)
	emu.register_frame_done(frame_done)
	emu.register_menu(menu_callback, menu_populate, 'Car simulator')
end

return exports
