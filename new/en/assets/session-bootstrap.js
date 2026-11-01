
let taskStopCapability = "";
if (/^#stop-updates=tw_[0-9a-f]{32}\.[0-9a-f]{64}$/.test(location.hash)) {
  taskStopCapability = location.hash.slice(14);
  history.replaceState(null, "", location.pathname + location.search + "#cancellation");
}


window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('consent', 'default', {
  'ad_storage': 'denied',
  'ad_user_data': 'denied',
  'ad_personalization': 'denied',
  'analytics_storage': 'denied'
});
