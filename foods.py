"""Food groups for the Nutrition tab, and a built-in list of common foods so
most new ingredients are classified automatically.

An ingredient belongs to one group. "other" means "not tracked" (pasta,
cheese, oil...); an ingredient with no group yet is shown as unclassified.
"""
import unicodedata

GROUPS = {
    "red_meat": "Red meat",
    "chicken": "Chicken",
    "processed_meat": "Processed meat",
    "oily_fish": "Oily fish",
    "white_fish": "White fish",
    "seafood": "Seafood",
    "legumes": "Legumes",
    "vegetables": "Vegetables",
    "other": "Not tracked",
}

# Goals can also target "fish": any of oily fish, white fish or seafood.
FISH = ("oily_fish", "white_fish", "seafood")
GOAL_GROUPS = {"fish": "Fish", **{k: v for k, v in GROUPS.items() if k != "other"}}
GOAL_KINDS = ("max", "min", "track", "off")

DEFAULT_GOALS = [
    # (group, kind, target)
    ("fish", "min", 3),
    ("vegetables", "min", 7),
    ("red_meat", "max", 2),
    ("chicken", "max", 3),
    ("processed_meat", "max", 2),
    ("legumes", "track", 2),
    ("oily_fish", "off", 2),
    ("white_fish", "off", 2),
    ("seafood", "off", 1),
]

_KNOWN = {
    "red_meat": """
        ternera, vaca, buey, carne picada, carne de ternera, filete, solomillo, entrecot, chuleton,
        albondigas, hamburguesa, cordero, cerdo, lomo, secreto, presa, pluma, costillas, chuletas,
        carrillada, rabo de toro, cabrito, beef, minced meat, ground beef, steak, lamb, pork,
        pork loin, meatballs, veal, mutton, ribs
    """,
    "chicken": """
        pollo, pechuga, pechuga de pollo, muslos de pollo, contramuslos, alitas, pavo, pechuga de pavo,
        chicken, chicken breast, chicken thighs, turkey
    """,
    "processed_meat": """
        jamon, jamon serrano, jamon iberico, jamon de york, jamon cocido, bacon, beicon, panceta,
        chorizo, salchichon, fuet, lomo embuchado, morcilla, salchichas, sobrasada, mortadela,
        pavo en lonchas, longaniza, ham, cured ham, cooked ham, sausage, sausages, salami, pepperoni,
        hot dog, frankfurt
    """,
    "oily_fish": """
        salmon, atun, atun filete, atun en lata, bonito, sardinas, caballa, boqueron, boquerones,
        anchoas, trucha, arenque, emperador, pez espada, jurel, chicharro, palometa, anguila,
        tuna, salmon fillet, sardines, mackerel, anchovies, trout, herring, swordfish
    """,
    "white_fish": """
        merluza, bacalao, dorada, lubina, rape, gallo, lenguado, rodaballo, abadejo, pescadilla,
        panga, mero, cabracho, besugo, varitas de merluza, cod, hake, sea bream, sea bass, sole,
        monkfish, haddock, pollock, halibut, turbot, fish fingers
    """,
    "seafood": """
        gambas, langostinos, gamba, mejillones, almejas, calamares, calamar, sepia, pulpo, chipirones,
        berberechos, navajas, vieiras, cangrejo, bogavante, cigalas, shrimp, prawns, mussels, clams,
        squid, octopus, cuttlefish, scallops, crab, lobster
    """,
    "legumes": """
        lentejas, garbanzos, alubias, judias blancas, judias pintas, frijoles, habas, guisantes secos,
        soja, edamame, falafel, hummus, tofu, tempeh, lentils, chickpeas, beans, kidney beans,
        black beans, white beans, split peas
    """,
    "vegetables": """
        verduras, verduras bolsa, verduras cocido, verdura, cebolla, cebolleta, puerro, zanahoria,
        calabacin, calabaza, berenjena, pimiento, pimiento rojo, pimiento verde, tomate,
        tomate triturado, tomate natural, brocoli, coliflor, repollo, col, coles de bruselas, lombarda,
        espinacas, acelgas, lechuga, canonigos, rucula, escarola, endivias, pepino, apio, alcachofas,
        esparragos, judias verdes, guisantes, maiz, champinones, setas, boletus, nabo, remolacha,
        gazpacho, salmorejo, wakame, algas, kale, onion, spring onion, leek, carrot, zucchini,
        courgette, pumpkin, squash, eggplant, aubergine, pepper, bell pepper, tomato, broccoli,
        cauliflower, cabbage, spinach, chard, lettuce, cucumber, celery, artichoke, asparagus,
        green beans, peas, corn, mushrooms, beetroot, seaweed
    """,
    "other": """
        aceite, aceite de oliva, sal, pimienta, ajo, harina, azucar, mantequilla, leche, nata, queso,
        queso rallado, queso en lonchas, queso fresco, mozzarella, parmesano, yogur, huevo, huevos,
        arroz, pasta, espaguetis, macarrones, fideos, pan, pan rallado, tortillas, wraps, migas,
        patata, patatas, pure de patata, batata, boniato, caldo, pimenton, comino, curry,
        cubos de curry, oregano, perejil, albahaca, laurel, mostaza, mayonesa, ketchup, vinagre,
        tomate frito, pesto, miso, salsa de soja, aguacate, limon, pepinillos, aceitunas, nueces,
        oil, olive oil, salt, black pepper, garlic, flour, sugar, butter, milk, cream, cheese,
        egg, eggs, rice, noodles, bread, breadcrumbs, potato, potatoes, sweet potato, stock, broth,
        paprika, cumin, herbs, mustard, vinegar, soy sauce, avocado, lemon
    """,
}


def normalize(name):
    """Lowercase, no accents, single spaces: 'Brócoli ' -> 'brocoli'."""
    text = unicodedata.normalize("NFKD", str(name).strip().lower())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


_LOOKUP = {normalize(food): group for group, foods in _KNOWN.items() for food in foods.split(",") if food.strip()}


def guess_group(name):
    """The group of a common food, or None if it isn't in the built-in list."""
    key = normalize(name)
    # Also try singular/plural: "sardina" matches "sardinas" and vice versa.
    candidates = [key, key + "s", key + "es"]
    if key.endswith("es"):
        candidates.append(key[:-2])
    if key.endswith("s"):
        candidates.append(key[:-1])
    return next((_LOOKUP[c] for c in candidates if c in _LOOKUP), None)
