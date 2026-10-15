import httpx

URL = "https://dev452436.service-now.com/api/now/table/incident"
USER = "api_user"
PASS = "O8JVD}8-02@hg8$BeQR?4%#,@&Ve)74"

r = httpx.get(
    URL,
    params={"sysparm_limit": 1},
    auth=(USER, PASS),
    headers={"Accept": "application/json"},
    timeout=30,
)
print(r.status_code)
print(r.headers)
print(r.text[:500])