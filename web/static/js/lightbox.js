// Lightbox for screenshot expansion
(function() {
    // Create overlay element
    const overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.innerHTML = '<img class="lightbox-img" /><div class="lightbox-caption"></div>';
    document.body.appendChild(overlay);

    const img = overlay.querySelector('.lightbox-img');
    const caption = overlay.querySelector('.lightbox-caption');

    // Click any content image to expand
    document.addEventListener('click', function(e) {
        const target = e.target;
        if (target.tagName === 'IMG' && target.closest('.video-content')) {
            img.src = target.src;
            caption.textContent = target.alt || '';
            overlay.classList.add('lightbox--visible');
        }
    });

    // Click overlay to close
    overlay.addEventListener('click', function() {
        overlay.classList.remove('lightbox--visible');
    });

    // Escape key to close
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            overlay.classList.remove('lightbox--visible');
        }
    });
})();
