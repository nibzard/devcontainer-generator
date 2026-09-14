function isValidGithubRepoUrl(url) {
  return /^https?:\/\/github\.com\/[\w-]+\/[\w.-]+\/?$/.test(url);
}

function repoUrlFromHash(hash) {
  const rawHash = (hash || "").replace(/^#/, "");
  if (!rawHash) return null;

  try {
    const repoUrl = decodeURIComponent(rawHash).trim();
    return isValidGithubRepoUrl(repoUrl) ? repoUrl : null;
  } catch (_error) {
    return null;
  }
}

function devcontainerEndpoint(repoUrl) {
  return `/devcontainer?repo_url=${encodeURIComponent(repoUrl)}`;
}

function redirectDevcontainerHash(locationObject) {
  const currentLocation = locationObject || window.location;
  if (currentLocation.pathname && currentLocation.pathname !== "/") return false;

  const repoUrl = repoUrlFromHash(currentLocation.hash);
  if (!repoUrl) return false;

  currentLocation.replace(devcontainerEndpoint(repoUrl));
  return true;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    devcontainerEndpoint,
    isValidGithubRepoUrl,
    redirectDevcontainerHash,
    repoUrlFromHash,
  };
}
