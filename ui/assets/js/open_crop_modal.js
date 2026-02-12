() => {
    setTimeout(() => {
        const dimElement = document.querySelector('#preprocess-dimensions-data');
        if (dimElement) {
            const width = parseInt(dimElement.dataset.width) || 0;
            const height = parseInt(dimElement.dataset.height) || 0;
            if (width > 0 && height > 0) {
                const imgContainer = document.querySelector('#conv-image-input');
                if (imgContainer) {
                    const img = imgContainer.querySelector('img');
                    if (img && img.src && typeof window.openCropModal === 'function') {
                        window.openCropModal(img.src, width, height, 0, 0);
                    }
                }
            }
        }
    }, 300);
}
