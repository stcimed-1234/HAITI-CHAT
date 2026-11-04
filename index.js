const menuHtn = document.getElementById('appMenuHtn');
const menuAppGoogle = document.getElementById('appMenuGoogle');

// Ouvrir/Fermer au clic sur le bouton
menuHtn.addEventListener('click', (event) => {
    event.stopPropagation();
    menuAppGoogle.classList.toggle('hidden');
});

// Fermer le menu si l'on clique en dehors
document.addEventListener('click', (event) => {
    if (!menuAppGoogle.contains(event.target) && !menuHtn.contains(event.target)) {
        menuAppGoogle.classList.add('hidden');
    }
});

const btn =
    document.getElementById('btn');
const menu =
    document.getElementById('menu');
btn.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    menu.style.top = `${e.clientY}px`;
    menu.style.left = `${e.clientX}px`;
    menu.style.display = 'block';
});
document.addEventListener('click', () => {
    menu.style.display = 'none';
});
