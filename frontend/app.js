const status = document.querySelector("#status");

try {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const health = await response.json();
  status.textContent = `API: ${health.status}`;
} catch {
  status.textContent = "API unavailable";
}
