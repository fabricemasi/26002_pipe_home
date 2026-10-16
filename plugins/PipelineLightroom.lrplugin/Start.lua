-- Fournit à Pipeline Browser les aperçus du catalogue via le SDK Lightroom.
-- Le protocole est constitué de champs hexadécimaux ; aucun code reçu n'est évalué.
if _G.PipelineBrowserProxyRunning then return end
_G.PipelineBrowserProxyRunning = true
-- Trace écrite indépendante du catalogue : permet de distinguer un script jamais
-- démarré d'une erreur survenue ensuite dans la boucle de surveillance.
do
    local ok, path = pcall(function() return _PLUGIN.path .. '/startup-diagnostic.txt' end)
    if ok then
        local file = io.open(path, 'wb')
        if file then
            file:write('Start.lua exécuté : ', os.date('%Y-%m-%d %H:%M:%S'), '\n')
            file:close()
        end
    end
end
local Tasks = import 'LrTasks'
local App = import 'LrApplication'
local AppView = import 'LrApplicationView'
local Files = import 'LrFileUtils'
local Paths = import 'LrPathUtils'
local function join(a, b) return Paths.child(a, b) end
local function read(path)
    local f = io.open(path, 'rb'); if not f then return nil end
    local text = f:read('*a'); f:close(); return text
end
local function write(path, text)
    local temp = path .. '.tmp'
    local f = assert(io.open(temp, 'wb')); assert(f:write(text)); f:close()
    if Files.exists(path) then Files.delete(path) end
    local moved, reason = Files.move(temp, path)
    assert(moved, reason or ('Impossible de déplacer le fichier temporaire vers ' .. path))
end
local function unhex(s)
    assert(#s % 2 == 0 and not s:find('[^%x]'), 'Champ mal encodé')
    return (s:gsub('..', function(cc) return string.char(tonumber(cc, 16)) end))
end
local function quote(s)
    return '"' .. tostring(s):gsub('[%z\1-\31\\"]', function(c)
        return string.format('\\u%04x', string.byte(c))
    end) .. '"'
end
local function json(v)
    if type(v) == 'string' then return quote(v) end
    if type(v) == 'number' or type(v) == 'boolean' then return tostring(v) end
    if v == nil then return 'null' end
    local out = {}
    for k, item in pairs(v) do out[#out + 1] = quote(k) .. ':' .. json(item) end
    return '{' .. table.concat(out, ',') .. '}'
end
local function canonical(p) return (p:gsub('/', '\\'):gsub('\\+$', ''):lower()) end
local busy = {}
local function findKeyword(keywords, wanted)
    for _, keyword in ipairs(keywords or {}) do
        if keyword:getName():lower() == wanted:lower() then return keyword end
        local found = findKeyword(keyword:getChildren(), wanted)
        if found then return found end
    end
end
local function setAttribute(catalog, photo, field, value)
    catalog:withWriteAccessDo('Pipeline Browser — ' .. field, function()
        if field == 'rating' then
            photo:setRawMetadata('rating', value == '' and nil or tonumber(value))
        elseif field == 'color' then
            local label = ''
            if value ~= '' then
                local labels = catalog:getLabelMapToColorName()
                label = labels[value] or value
            end
            photo:setRawMetadata('label', label)
        elseif field == 'status' then
            photo:setRawMetadata('pickStatus', tonumber(value))
        elseif field == 'keywords' then
            local wanted = {}
            for word in (value .. '\n'):gmatch('(.-)\n') do
                if word ~= '' then wanted[word:lower()] = word end
            end
            for _, keyword in ipairs(photo:getRawMetadata('keywords') or {}) do
                if not wanted[keyword:getName():lower()] then photo:removeKeyword(keyword) end
            end
            for normalized, word in pairs(wanted) do
                local keyword = findKeyword(catalog:getKeywords(), word)
                if not keyword then keyword = catalog:createKeyword(word, {}, true, nil, true) end
                if keyword then photo:addKeyword(keyword) end
            end
        else
            error('Attribut non pris en charge: ' .. tostring(field))
        end
    end)
end
local function process(root, expected, path)
    local text = read(path); if not text then return end
    local fields = {}
    for token in (text:gsub('[\r\n]+$', '') .. '\t'):gmatch('(.-)\t') do fields[#fields + 1] = unhex(token) end
    assert(#fields == 9, 'Version de protocole inconnue')
    local id, op, uuid, _field, _before, _value, target, _collection, catalogPath = unpack(fields)
    assert(id:match('^[%w_]+$'), 'Identifiant invalide')
    if busy[id] then return end
    local replyPath = join(join(root, 'replies'), id .. '.json')
    if Files.exists(replyPath) then Files.delete(path); return end
    if canonical(expected) ~= canonical(catalogPath) then return end
    busy[id] = true
    local function reply(extra)
        extra.id, extra.catalog = id, expected
        write(replyPath, json(extra)); Files.delete(path); busy[id] = nil
    end
    local ok, err = Tasks.pcall(function()
        local catalog = App.activeCatalog()
        assert(canonical(catalog:getPath()) == canonical(expected), 'Le catalogue actif a changé')
        local photo = assert(catalog:findPhotoByUuid(uuid), 'Photo absente du catalogue')
        if op == 'profile' then
            local settings = photo:getDevelopSettings() or {}
            local look = settings.Look
            local profile = type(look) == 'table' and look.Name or nil
            local baseProfile = settings.CameraProfile
            if not profile or profile == '' then profile = baseProfile end
            reply({ ok = true, profile = profile or '', baseProfile = baseProfile or '',
                    amount = settings.ProfileAmount or 100 })
        elseif op == 'preview' then
            assert(target:match('^[%w_%-]+%.jpg$'), 'Nom de proxy invalide')
            photo:requestJpegThumbnail(2560, 2560, function(data, why)
                local worked, reason = pcall(function()
                    if not data then reply({ error = why or 'Aperçu Lightroom indisponible' }); return end
                    write(join(join(root, 'images'), target), data)
                    reply({ ok = true })
                end)
                if not worked then busy[id] = nil end
            end)
        elseif op == 'set' then
            setAttribute(catalog, photo, _field, _value)
            reply({ ok = true })
        elseif op == 'open' then
            local photoPath = assert(photo:getRawMetadata('path'), 'Chemin de la photo indisponible dans Lightroom')
            assert(canonical(photoPath) == canonical(target),
                'La photo du catalogue ne correspond pas au fichier en focus')
            local folder = assert(catalog:getFolderByPath(Paths.parent(photoPath)),
                'Dossier de la photo introuvable dans Lightroom')
            AppView.switchToModule('library')
            for _ = 1, 30 do
                if AppView.getCurrentModuleName() == 'library' then break end
                Tasks.sleep(0.1)
            end
            assert(AppView.getCurrentModuleName() == 'library',
                'Lightroom n’a pas ouvert le mode Bibliothèque')
            assert(catalog:setActiveSources({ folder }), 'Impossible d’activer le dossier de la photo')
            -- Lightroom met à jour la grille après le retour de setActiveSources.
            -- Une sélection immédiate est parfois ignorée par son interface.
            Tasks.sleep(0.2)
            local function correctSource(sources)
                if #sources ~= 1 then return false end
                local ok, activeFolderPath = pcall(function() return sources[1]:getPath() end)
                return ok and activeFolderPath and canonical(activeFolderPath) == canonical(folder:getPath())
            end
            local sources = catalog:getActiveSources()
            for _ = 1, 20 do
                if correctSource(sources) then break end
                Tasks.sleep(0.1)
                sources = catalog:getActiveSources()
            end
            -- L’interface peut avoir basculé sur le bon dossier alors que le SDK
            -- renvoie encore une source périmée. Ne pas interrompre ici : c’était
            -- précisément ce qui empêchait la sélection et le passage en Développement.
            local selected
            local function selectInCurrentSource()
                for _ = 1, 20 do
                    catalog:setSelectedPhotos(photo, { photo })
                    Tasks.sleep(0.1)
                    selected = catalog:getTargetPhoto()
                    if selected and selected:getRawMetadata('uuid') == uuid then return true end
                end
                return false
            end
            local selectedInFolder = selectInCurrentSource()
            if not selectedInFolder then
                -- setSelectedPhotos ne peut sélectionner qu’une photo présente dans
                -- la source active. All Photographs sert de source de secours fiable.
                assert(catalog:setActiveSources({ catalog.kAllPhotos }),
                    'Impossible d’activer Toutes les photos pour sélectionner la cible')
                Tasks.sleep(0.4)
                assert(selectInCurrentSource(), 'Lightroom n’a pas sélectionné la photo demandée')
            end
            -- Laisser Bibliothèque appliquer la sélection avant de changer de module.
            -- Sans cette pause, quand Develop était déjà ouvert, Lightroom pouvait
            -- y revenir sur l’ancienne photo malgré le TargetPhoto actualisé.
            Tasks.sleep(0.5)
            local function isRequestedPhoto(candidate)
                if not candidate then return false end
                local ok, selectedUuid = pcall(function() return candidate:getRawMetadata('uuid') end)
                local pathOk, selectedPath = pcall(function() return candidate:getRawMetadata('path') end)
                return ok and selectedUuid == uuid and pathOk and selectedPath
                    and canonical(selectedPath) == canonical(target)
            end
            local opened = false
            for attempt = 1, 2 do
                AppView.switchToModule('develop')
                for _ = 1, 40 do
                    if AppView.getCurrentModuleName() == 'develop' then break end
                    Tasks.sleep(0.1)
                end
                if AppView.getCurrentModuleName() == 'develop' then
                    -- Le nom du module change avant que la vue Develop ait toujours
                    -- fini de charger la photo : attendre puis vérifier UUID ET chemin.
                    Tasks.sleep(0.6)
                    selected = catalog:getTargetPhoto()
                    if isRequestedPhoto(selected) then
                        opened = true
                        break
                    end
                end
                if attempt < 2 then
                    AppView.switchToModule('library')
                    for _ = 1, 40 do
                        if AppView.getCurrentModuleName() == 'library' then break end
                        Tasks.sleep(0.1)
                    end
                    assert(AppView.getCurrentModuleName() == 'library',
                        'Lightroom n’a pas quitté le mode Développement pour actualiser la photo')
                    assert(catalog:setActiveSources({ catalog.kAllPhotos }),
                        'Impossible de réactiver Toutes les photos pour actualiser Développement')
                    Tasks.sleep(0.5)
                    assert(selectInCurrentSource(),
                        'Lightroom n’a pas conservé la photo demandée dans Bibliothèque')
                    Tasks.sleep(0.5)
                end
            end
            assert(opened, 'Lightroom est resté sur une autre photo dans le mode Développement')
            reply({ ok = true, path = photoPath, uuid = uuid,
                    folder = folder:getPath(), module = AppView.getCurrentModuleName() })
        else
            error('Commande Lightroom non prise en charge')
        end
    end)
    if not ok then reply({ error = tostring(err) }) end
end

Tasks.startAsyncTask(function()
    while _G.PipelineBrowserProxyRunning do
        local ok, err = Tasks.pcall(function()
            local connection = read(join(_PLUGIN.path, 'connection.txt'))
            if not connection then return end
            local encodedRoot, encodedCatalog = connection:match('([%x]+)[\r\n]+([%x]+)')
            if not encodedRoot then return end
            local root, expected = unhex(encodedRoot), unhex(encodedCatalog)
            local catalog = App.activeCatalog()
            local activePath = catalog:getPath()
            write(join(root, 'status.json'), json {
                catalog = activePath, expectedCatalog = expected, time = os.time(),
                labels = catalog:getLabelMapToColorName(),
            })
            local paths = {}
            for path in Files.files(join(root, 'requests')) do
                if path:match('%.req$') then
                    local request = read(path) or ''
                    local opHex = request:match('^[%x]+\t([%x]+)\t')
                    local priority = opHex and unhex(opHex) == 'open' and 0 or 1
                    paths[#paths + 1] = { path = path, priority = priority, request = request }
                end
            end
            table.sort(paths, function(a, b)
                if a.priority ~= b.priority then return a.priority < b.priority end
                if a.priority == 0 then return a.path > b.path end
                return a.path < b.path
            end)
            -- Pour une ouverture, seul le clic le plus récent compte : les demandes
            -- précédentes pourraient sinon replacer Lightroom sur une ancienne photo.
            local keptOpen = false
            for _, item in ipairs(paths) do
                if item.priority == 0 then
                    if keptOpen then Files.delete(item.path) else keptOpen = true end
                end
            end
            for i = 1, math.min(#paths, 8) do
                if not _G.PipelineBrowserProxyRunning then break end
                process(root, expected, paths[i].path); Tasks.yield()
            end
        end)
        if not ok then
            local log = io.open(join(_PLUGIN.path, 'last-error.txt'), 'wb')
            if log then log:write(tostring(err)); log:close() end
        end
        Tasks.sleep(1)
    end
end)
