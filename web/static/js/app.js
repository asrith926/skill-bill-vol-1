// Scroll-spy for chapter navigation + general interactions
(function() {
    // Build chapter nav from h2 elements
    const content = document.querySelector('.video-content');
    const navContainer = document.getElementById('chapter-nav-links');

    if (content && navContainer) {
        const headings = content.querySelectorAll('h2');
        headings.forEach((h, i) => {
            // Assign ID for anchor linking
            const id = 'chapter-' + i;
            h.id = id;

            const link = document.createElement('a');
            link.href = '#' + id;
            link.textContent = h.textContent;
            navContainer.appendChild(link);
        });

        // Scroll-spy
        const tocLinks = navContainer.querySelectorAll('a');
        if (headings.length && tocLinks.length) {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const id = entry.target.id;
                        tocLinks.forEach(link => {
                            link.classList.toggle('chapter-nav--active', link.getAttribute('href') === `#${id}`);
                        });
                    }
                });
            }, { rootMargin: '-80px 0px -70% 0px' });

            headings.forEach(h => observer.observe(h));
        }
    }

    // Mobile sidebar toggle
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', () => {
            sidebar.classList.toggle('sidebar--open');
        });
    }
})();
