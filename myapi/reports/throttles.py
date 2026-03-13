from rest_framework.throttling import SimpleRateThrottle

class DeviceAndIPRateThrottle(SimpleRateThrottle):
    """
    Limits the rate of API requests based on a combination of the client's IP address 
    AND their Device ID. This makes rate-limiting much more robust against simple 
    IP spoofing or VPN switching.
    """
    scope = 'report_submit'

    def get_cache_key(self, request, view):
        # 1. Retrieve Client IP Address using DRF's built-in get_ident method
        # It automatically checks HTTP_X_FORWARDED_FOR and REMOTE_ADDR
        ip_addr = self.get_ident(request)

        # 2. Extract Device ID from request payload or fallback to headers
        # The mobile app sends device_id inside the FormData payload
        device_id = request.data.get('device_id')
        if not device_id:
            device_id = request.META.get('HTTP_X_DEVICE_ID', 'unknown_device')

        # 3. Create a unique identifier combining IP and Device ID
        unique_ident = f"{ip_addr}_{device_id}"

        # 4. Format the final cache key
        return self.cache_format % {
            'scope': self.scope,
            'ident': unique_ident
        }
