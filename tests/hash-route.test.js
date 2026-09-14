const test = require("node:test");
const assert = require("node:assert/strict");

const {
  devcontainerEndpoint,
  redirectDevcontainerHash,
  repoUrlFromHash,
} = require("../js/hash-route.js");

test("extracts plain and URL-encoded GitHub repository hashes", () => {
  const repoUrl = "https://github.com/daytonaio/daytona";

  assert.equal(repoUrlFromHash(`#${repoUrl}`), repoUrl);
  assert.equal(repoUrlFromHash(`#${encodeURIComponent(repoUrl)}`), repoUrl);
});

test("ignores missing, malformed, and non-repository hashes", () => {
  assert.equal(repoUrlFromHash(""), null);
  assert.equal(repoUrlFromHash("#not-a-url"), null);
  assert.equal(repoUrlFromHash("#https://example.com/owner/repo"), null);
  assert.equal(repoUrlFromHash("#%E0%A4%A"), null);
});

test("builds the scriptable plain-text endpoint", () => {
  assert.equal(
    devcontainerEndpoint("https://github.com/daytonaio/daytona"),
    "/devcontainer?repo_url=https%3A%2F%2Fgithub.com%2Fdaytonaio%2Fdaytona",
  );
});

test("redirects valid browser hashes to the endpoint", () => {
  let destination = null;
  const locationObject = {
    hash: "#https://github.com/daytonaio/daytona",
    pathname: "/",
    replace(value) {
      destination = value;
    },
  };

  assert.equal(redirectDevcontainerHash(locationObject), true);
  assert.equal(
    destination,
    "/devcontainer?repo_url=https%3A%2F%2Fgithub.com%2Fdaytonaio%2Fdaytona",
  );
});

test("does not redirect invalid browser hashes", () => {
  let redirected = false;
  const locationObject = {
    hash: "#not-a-repository",
    pathname: "/",
    replace() {
      redirected = true;
    },
  };

  assert.equal(redirectDevcontainerHash(locationObject), false);
  assert.equal(redirected, false);
});

test("does not redirect repository hashes on other pages", () => {
  let redirected = false;
  const locationObject = {
    hash: "#https://github.com/daytonaio/daytona",
    pathname: "/manifesto",
    replace() {
      redirected = true;
    },
  };

  assert.equal(redirectDevcontainerHash(locationObject), false);
  assert.equal(redirected, false);
});
