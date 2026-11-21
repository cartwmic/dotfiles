package server

func createMessageCache(conf *Config, pool *db.DB) (*message.Cache, error) {
	if conf.CacheDuration == 0 {
		return message.NewNopStore()
	} else if pool != nil {
		return message.NewPostgresStore(pool, conf.CacheBatchSize, conf.CacheBatchTimeout)
	} else if conf.CacheFile != "" {
		return message.NewSQLiteStore(conf.CacheFile, conf.CacheStartupQueries, conf.CacheDuration, conf.CacheBatchSize, conf.CacheBatchTimeout, false)
	}
	return message.NewMemStore()
}
