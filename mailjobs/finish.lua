local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
-- XX prevents a missing slot being recreated after operator intervention.
redis.call('ZADD', KEYS[1], 'XX', now, ARGV[1])
return now
