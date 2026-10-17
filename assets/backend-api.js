/* Same-origin API client. No Supabase credentials are delivered to the browser. */
window.SeatSpotAPI = (() => {
  async function request(action, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`/api/seatspot?action=${encodeURIComponent(action)}`, {
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      });
      let data;
      try { data = await response.json(); } catch { throw new Error('Cookie ordering is unavailable. Please try again.'); }
      if (!response.ok) {
        const error = new Error(data.error?.message || 'The request could not be completed.');
        error.code = data.error?.code; error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The request timed out. Reconnecting to check your order…');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  return { request, escape };
})();
