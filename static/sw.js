const CACHE_NAME = "reup-nvl-vip-v1";

self.addEventListener(
    "install",
    function(event) {
        self.skipWaiting();
    }
);

self.addEventListener(
    "activate",
    function(event) {
        event.waitUntil(
            self.clients.claim()
        );
    }
);

self.addEventListener(
    "fetch",
    function(event) {

        const request =
            event.request;

        if (
            request.method !== "GET"
        ) {
            return;
        }

        const url =
            new URL(
                request.url
            );

        if (
            url.pathname.startsWith(
                "/static/"
            )
        ) {

            event.respondWith(

                caches.match(
                    request
                ).then(
                    function(cached) {

                        if (cached) {
                            return cached;
                        }

                        return fetch(
                            request
                        ).then(
                            function(response) {

                                const copy =
                                    response.clone();

                                caches.open(
                                    CACHE_NAME
                                ).then(
                                    function(cache) {

                                        cache.put(
                                            request,
                                            copy
                                        );

                                    }
                                );

                                return response;
                            }
                        );
                    }
                )
            );
        }
    }
);
