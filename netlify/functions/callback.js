const REDIRECT_URL = "https://jlt.digital/api/callback";
const SITE_ORIGIN = "https://jlt.digital";

exports.handler = async function (event) {
  const params = event.queryStringParameters || {};
  if (params.error) {
    return script("error", { message: params.error_description || params.error });
  }

  const state = params.state || "";
  const cookie = readCookie(event.headers.cookie || event.headers.Cookie || "", "decap_oauth_state");
  if (!state || state !== cookie) {
    return script("error", { message: "Login expired. Close this window and try again." });
  }

  const clientId = process.env.GITHUB_CLIENT_ID;
  const clientSecret = process.env.GITHUB_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    return script("error", { message: "GitHub login is missing its Netlify environment variables." });
  }

  const tokenResponse = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "User-Agent": "jlt-digital",
    },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      code: params.code,
      redirect_uri: REDIRECT_URL,
    }),
  });
  const result = await tokenResponse.json();
  if (!result.access_token) {
    return script("error", { message: result.error_description || result.error || "GitHub did not return a token." });
  }

  return script("success", { token: result.access_token, provider: "github" });
};

function readCookie(header, name) {
  const match = header.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[1]) : "";
}

function script(status, content) {
  const payload = JSON.stringify(content).replace(/</g, "\\u003c");
  const body = `<!DOCTYPE html>
<html><body><script>
(function () {
  var status = ${JSON.stringify(status)};
  var payload = ${payload};
  function receive(event) {
    if (event.origin !== ${JSON.stringify(SITE_ORIGIN)}) return;
    window.opener.postMessage("authorization:github:" + status + ":" + JSON.stringify(payload), event.origin);
    window.removeEventListener("message", receive, false);
  }
  window.addEventListener("message", receive, false);
  if (window.opener) window.opener.postMessage("authorizing:github", ${JSON.stringify(SITE_ORIGIN)});
})();
</script></body></html>`;
  return {
    statusCode: 200,
    multiValueHeaders: {
      "Set-Cookie": ["decap_oauth_state=; HttpOnly; Secure; Path=/; Max-Age=0; SameSite=Lax"],
    },
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
    body,
  };
}
