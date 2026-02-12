(function() {
    function getRootFromEvent(event) {
        const target = event && event.target;
        if (!target || !target.closest) return null;
        return target.closest("#conv-preview");
    }

    function getRoot() {
        return document.getElementById("conv-preview");
    }

    function getViewport(root) {
        return root.querySelector(".image-container") || root;
    }

    function getMedia(root) {
        return root.querySelector("canvas, img");
    }

    function ensureBase(media) {
        const baseW = media.naturalWidth || media.width;
        const baseH = media.naturalHeight || media.height;
        if (!baseW || !baseH) return false;
        const sizeKey = `${baseW}x${baseH}`;
        if (media.dataset.baseSize !== sizeKey) {
            media.dataset.baseSize = sizeKey;
            media.dataset.baseW = baseW;
            media.dataset.baseH = baseH;
        }
        return true;
    }

    function setZoom(media, zoom) {
        const bw = parseFloat(media.dataset.baseW || media.width);
        const bh = parseFloat(media.dataset.baseH || media.height);
        const z = Math.max(0.2, Math.min(4, zoom));
        media.style.width = `${bw * z}px`;
        media.style.height = `${bh * z}px`;
        media.dataset.zoom = z.toFixed(3);
    }

    function fitToView(root, media) {
        const viewport = getViewport(root);
        const bw = parseFloat(media.dataset.baseW || media.width);
        const bh = parseFloat(media.dataset.baseH || media.height);
        const vw = viewport.clientWidth || root.clientWidth;
        const vh = viewport.clientHeight || root.clientHeight;
        if (!vw || !vh) {
            setZoom(media, 1);
            return;
        }
        const fitZoom = Math.min(vw / bw, vh / bh, 1);
        setZoom(media, fitZoom);
    }

    function handleWheel(e) {
        const root = getRootFromEvent(e);
        if (!root) return;
        const media = getMedia(root);
        if (!media) return;
        if (!ensureBase(media)) return;
        e.preventDefault();
        const current = parseFloat(media.dataset.zoom || "1");
        const delta = e.deltaY < 0 ? 0.1 : -0.1;
        setZoom(media, current + delta);
    }

    function handleDoubleClick(e) {
        const root = getRootFromEvent(e);
        if (!root) return;
        const media = getMedia(root);
        if (!media) return;
        if (!ensureBase(media)) return;
        e.preventDefault();
        fitToView(root, media);
    }

    function bindGlobalHandlers() {
        if (document.body && !document.body.dataset.previewZoomBound) {
            document.body.dataset.previewZoomBound = "1";
            document.addEventListener("wheel", handleWheel, { passive: false });
            document.addEventListener("dblclick", handleDoubleClick);
        }
    }

    function observeRoot() {
        const root = getRoot();
        if (!root) return false;
        if (root.dataset.zoomObserver) return true;
        root.dataset.zoomObserver = "1";
        const observer = new MutationObserver(() => {
            const media = getMedia(root);
            if (!media) return;
            if (!ensureBase(media)) return;
            const sizeKey = media.dataset.baseSize || "";
            const currentZoom = parseFloat(media.dataset.zoom || "0");
            if (currentZoom === 0 || media.dataset.lastFitSize !== sizeKey) {
                media.dataset.lastFitSize = sizeKey;
                setTimeout(() => fitToView(root, media), 0);
            }
        });
        observer.observe(root, { childList: true, subtree: true });
        return true;
    }

    function waitForRoot() {
        if (observeRoot()) return;
        const bodyObserver = new MutationObserver(() => {
            if (observeRoot()) {
                bodyObserver.disconnect();
            }
        });
        bodyObserver.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            bindGlobalHandlers();
            waitForRoot();
        });
    } else {
        bindGlobalHandlers();
        waitForRoot();
    }
})();
