local App = import 'LrApplication'
local Dialogs = import 'LrDialogs'

local function read(path)
    local file = io.open(path, 'rb')
    if not file then return nil end
    local content = file:read('*a')
    file:close()
    return content
end

local function unhex(value)
    return (value:gsub('..', function(pair) return string.char(tonumber(pair, 16)) end))
end

local catalog = App.activeCatalog()
local started = read(_PLUGIN.path .. '/startup-diagnostic.txt')
local connection = read(_PLUGIN.path .. '/connection.txt') or ''
local rootHex = connection:match('^([%x]+)')
local status = rootHex and read(unhex(rootHex) .. '/status.json') or nil
local timestamp = status and tonumber(status:match('"time":(%d+)')) or 0
local message
if not started then
    message = 'Le module de connexion ne semble pas avoir démarré. Redémarrez Lightroom Classic.'
elseif os.time() - timestamp > 5 then
    message = 'Le module a démarré, mais sa surveillance ne répond pas.\n' .. started
else
    message = 'Connexion active.\n' .. started
end
Dialogs.message('Pipeline Browser', message .. '\nCatalogue ouvert : ' .. catalog:getPath())
