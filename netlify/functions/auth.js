const REDIRECT_URL = "https://jlt.digital/api/callback";
const ALLOWED_SCOPE = "repo";

exports.handler = async function (event) {
  const clientId = process.env.GITHUB_CLIENT_ID;
  if (!clientId) {
    return html(500, "GitHub login is missing GITHUB_CLIENT_ID in the Netlify environment.");
  }

  const requested = new URLSearchParams(event.rawQuery || "").get("scope") || ALLOWED_SCOPE;
  const scope = requested
    .split(/[,\s]+/)
    .filter((part) => part === "repo" || part === "public_repo")
    .join(" ") || ALLOWED_SCOPE;
  const state = crypto.randomUUID();
  const authorize = new URL("https://github.com/login/oauth/authorize");
  authorize.searchParams.set("client_id", clientId);
  authorize.searchParams.set("redirect_uri", REDIRECT_URL);
  authorize.searchParams.set("scope", scope);
  authorize.searchParams.set("state", state);

  return {
    statusCode: 302,
    headers: {
      Location: authorize.toString(),
      "Cache-Control": "no-store",
      "Set-Cookie": `decap_oauth_state=${state}; HttpOnly; Secure; Path=/; Max-Age=600; SameSite=Lax`,
    },
  };
};

function html(statusCode, message) {
  return {
    statusCode,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    body: `<!DOCTYPE html><html><body><p>${message}</p></body></html>`,
  };
}
