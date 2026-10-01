(function () {
	var hash = window.location.hash;

	if (!hash || hash.length < 2 || !window.history.replaceState) {
		return;
	}

	var id = decodeURIComponent(hash.slice(1));

	function jumpTo(top) {
		var root = document.documentElement;
		var previous = root.style.scrollBehavior;
		root.style.scrollBehavior = 'auto';
		window.scrollTo(0, top);
		root.style.scrollBehavior = previous;
	}

	if (window.history.scrollRestoration) {
		window.history.scrollRestoration = 'manual';
	}

	window.history.replaceState(null, '', window.location.pathname + window.location.search);
	jumpTo(0);

	window.addEventListener('load', function () {
		var target = document.getElementById(id);

		function restoreHistory() {
			if (window.history.scrollRestoration) {
				window.history.scrollRestoration = 'auto';
			}
		}

		if (!target) {
			window.history.replaceState(null, '', hash);
			restoreHistory();
			return;
		}

		var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

		window.requestAnimationFrame(function () {
			jumpTo(0);
			target.scrollIntoView({
				behavior: reduce ? 'auto' : 'smooth',
				block: 'start'
			});
			window.history.replaceState(null, '', hash);
			window.addEventListener('scrollend', restoreHistory, { once: true });
			window.setTimeout(restoreHistory, 2000);
		});
	});
})();
