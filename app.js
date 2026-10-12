const RAW_ITEMS = {
  "Iron Ore": { label: "Железная руда", icon: "◆", group: "Руда" },
  "Copper Ore": { label: "Медная руда", icon: "◈", group: "Руда" },
  "Limestone": { label: "Известняк", icon: "◌", group: "Руда" },
  "Coal": { label: "Уголь", icon: "⬟", group: "Руда" },
  "Raw Quartz": { label: "Кварц", icon: "◇", group: "Руда" }
};

const MACHINE_META = {
  "Smelter": { label: "Плавильня", icon: "▣", power: 4 },
  "Constructor": { label: "Конструктор", icon: "⌑", power: 4 },
  "Assembler": { label: "Сборщик", icon: "▤", power: 15 },
  "Foundry": { label: "Литейный завод", icon: "▥", power: 16 },
  "Manufacturer": { label: "Производитель", icon: "▦", power: 55 },
  "Refinery": { label: "Нефтеперерабатывающий завод", icon: "▧", power: 30 }
};

// Rates are the default-recipe input/output rates at 100% clock speed (items per minute).
// This starter set intentionally focuses on common early/mid-game recipes.
const RECIPES = [
  { id: "iron-ingot", item: "Iron Ingot", machine: "Smelter", output: 30, inputs: [{ item: "Iron Ore", rate: 30 }] },
  { id: "copper-ingot", item: "Copper Ingot", machine: "Smelter", output: 30, inputs: [{ item: "Copper Ore", rate: 30 }] },
  { id: "steel-ingot", item: "Steel Ingot", machine: "Foundry", output: 45, inputs: [{ item: "Iron Ore", rate: 45 }, { item: "Coal", rate: 45 }] },
  { id: "quartz-crystal", item: "Quartz Crystal", machine: "Constructor", output: 22.5, inputs: [{ item: "Raw Quartz", rate: 37.5 }] },
  { id: "silica", item: "Silica", machine: "Constructor", output: 37.5, inputs: [{ item: "Raw Quartz", rate: 22.5 }] },
  { id: "iron-plate", item: "Iron Plate", machine: "Constructor", output: 20, inputs: [{ item: "Iron Ingot", rate: 30 }] },
  { id: "iron-rod", item: "Iron Rod", machine: "Constructor", output: 15, inputs: [{ item: "Iron Ingot", rate: 15 }] },
  { id: "screw", item: "Screw", machine: "Constructor", output: 40, inputs: [{ item: "Iron Rod", rate: 10 }] },
  { id: "wire", item: "Wire", machine: "Constructor", output: 30, inputs: [{ item: "Copper Ingot", rate: 15 }] },
  { id: "cable", item: "Cable", machine: "Constructor", output: 30, inputs: [{ item: "Wire", rate: 60 }] },
  { id: "concrete", item: "Concrete", machine: "Constructor", output: 15, inputs: [{ item: "Limestone", rate: 45 }] },
  { id: "copper-sheet", item: "Copper Sheet", machine: "Constructor", output: 10, inputs: [{ item: "Copper Ingot", rate: 20 }] },
  { id: "steel-beam", item: "Steel Beam", machine: "Constructor", output: 15, inputs: [{ item: "Steel Ingot", rate: 60 }] },
  { id: "steel-pipe", item: "Steel Pipe", machine: "Constructor", output: 20, inputs: [{ item: "Steel Ingot", rate: 30 }] },
  { id: "reinforced-plate", item: "Reinforced Iron Plate", machine: "Assembler", output: 5, inputs: [{ item: "Iron Plate", rate: 30 }, { item: "Screw", rate: 60 }] },
  { id: "modular-frame", item: "Modular Frame", machine: "Assembler", output: 2, inputs: [{ item: "Reinforced Iron Plate", rate: 3 }, { item: "Iron Rod", rate: 12 }] },
  { id: "rotor", item: "Rotor", machine: "Assembler", output: 4, inputs: [{ item: "Iron Rod", rate: 20 }, { item: "Screw", rate: 100 }] },
  { id: "stator", item: "Stator", machine: "Assembler", output: 5, inputs: [{ item: "Steel Pipe", rate: 15 }, { item: "Wire", rate: 40 }] },
  { id: "motor", item: "Motor", machine: "Assembler", output: 5, inputs: [{ item: "Rotor", rate: 10 }, { item: "Stator", rate: 10 }] },
  { id: "encased-beam", item: "Encased Industrial Beam", machine: "Assembler", output: 6, inputs: [{ item: "Steel Beam", rate: 24 }, { item: "Concrete", rate: 30 }] }
];

const ITEM_LABELS = {
  "Iron Ingot": "Железный слиток",
  "Copper Ingot": "Медный слиток",
  "Steel Ingot": "Стальной слиток",
  "Quartz Crystal": "Кварцевый кристалл",
  "Silica": "Кремнезём",
  "Iron Plate": "Железная плита",
  "Iron Rod": "Железный стержень",
  "Screw": "Винт",
  "Wire": "Проволока",
  "Cable": "Кабель",
  "Concrete": "Бетон",
  "Copper Sheet": "Медный лист",
  "Steel Beam": "Стальная балка",
  "Steel Pipe": "Стальная труба",
  "Reinforced Iron Plate": "Армированная железная плита",
  "Modular Frame": "Модульная рама",
  "Rotor": "Ротор",
  "Stator": "Статор",
  "Motor": "Мотор",
  "Encased Industrial Beam": "Обшитая промышленная балка"
};

const ITEM_ICONS = {
  "Iron Ingot": "▰", "Copper Ingot": "▰", "Steel Ingot": "▰", "Quartz Crystal": "◇", Silica: "◈",
  "Iron Plate": "▱", "Iron Rod": "╱", Screw: "⌁", Wire: "⌇", Cable: "⌇", Concrete: "▧",
  "Copper Sheet": "▱", "Steel Beam": "╋", "Steel Pipe": "◉", "Reinforced Iron Plate": "▦",
  "Modular Frame": "▤", Rotor: "◉", Stator: "◍", Motor: "◉", "Encased Industrial Beam": "▥"
};

const $ = (selector) => document.querySelector(selector);
const productSelect = $("#product-select");
const productSearch = $("#product-search");
const recipeSelect = $("#recipe-select");
const rateInput = $("#rate-input");
const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const preciseFormat = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
const recipeById = new Map(RECIPES.map((recipe) => [recipe.id, recipe]));
let lastToastTimer;
let currentPlan = null;

function readPreference(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function savePreference(key, value) {
  try { localStorage.setItem(key, value); } catch { /* Storage may be unavailable for file:// or private browsing. */ }
}

function parseRate(value) {
  const normalized = String(value).trim().replace(/\s+/g, "").replace(",", ".");
  return normalized ? Number(normalized) : NaN;
}

function formatNumber(value, precise = false) {
  const safe = Math.abs(value) < 0.000001 ? 0 : value;
  return (precise ? preciseFormat : numberFormat).format(safe);
}

function itemLabel(item) {
  return ITEM_LABELS[item] || RAW_ITEMS[item]?.label || item;
}

function populateProducts() {
  const availableItems = [...new Set(RECIPES.map((recipe) => recipe.item))];
  availableItems.sort((a, b) => itemLabel(a).localeCompare(itemLabel(b), "ru"));
  for (const item of availableItems) {
    const option = document.createElement("option");
    option.value = item;
    option.textContent = itemLabel(item);
    productSelect.append(option);
  }
  const savedProduct = readPreference("ficsit-product");
  if (savedProduct && availableItems.includes(savedProduct)) productSelect.value = savedProduct;
  else if (availableItems.includes("Iron Plate")) productSelect.value = "Iron Plate";
}

function filterProductOptions() {
  const query = productSearch.value.trim().toLocaleLowerCase("ru");
  const options = [...productSelect.options];
  let matches = 0;
  for (const option of options) {
    const isMatch = !query || option.textContent.toLocaleLowerCase("ru").includes(query) || option.value.toLocaleLowerCase("ru").includes(query);
    option.hidden = Boolean(query && !isMatch && option.value !== productSelect.value);
    if (isMatch) matches += 1;
  }
  const matchWord = new Intl.PluralRules("ru").select(matches);
  const matchLabel = { one: "совпадение", few: "совпадения", many: "совпадений", other: "совпадения" }[matchWord];
  $("#product-search-status").textContent = query
    ? (matches ? `${matches} ${matchLabel}` : "Ничего не найдено — измени или очисти запрос.")
    : "";
}

function populateRecipes(preferredId = recipeSelect.value) {
  const item = productSelect.value;
  const choices = RECIPES.filter((recipe) => recipe.item === item);
  recipeSelect.replaceChildren();
  for (const recipe of choices) {
    const option = document.createElement("option");
    option.value = recipe.id;
    const machine = MACHINE_META[recipe.machine]?.label || recipe.machine;
    option.textContent = `Базовый рецепт · ${machine}`;
    recipeSelect.append(option);
  }
  recipeSelect.disabled = choices.length <= 1;
  $("#recipe-select-group").hidden = choices.length <= 1;
  const chosen = choices.find((recipe) => recipe.id === preferredId) || choices[0];
  if (chosen) {
    recipeSelect.value = chosen.id;
    const ingredients = chosen.inputs.map((input) => `${formatNumber(input.rate)} ${itemLabel(input.item).toLowerCase()}`).join(" + ");
    $("#recipe-hint").textContent = `${ingredients} → ${formatNumber(chosen.output)} ${itemLabel(chosen.item).toLowerCase()} / мин`;
  } else {
    $("#recipe-hint").textContent = "Для этого продукта пока нет рецепта.";
  }
}

function calculatePlan(targetItem, targetRate, selectedRecipeId) {
  const machines = new Map();
  const raw = new Map();
  const path = [];
  let order = 0;

  function expand(item, requiredRate, depth) {
    if (requiredRate <= 0) return;
    if (RAW_ITEMS[item]) {
      raw.set(item, (raw.get(item) || 0) + requiredRate);
      return;
    }
    if (path.includes(item)) throw new Error(`Обнаружен цикл рецептов: ${[...path, item].map(itemLabel).join(" → ")}`);
    const candidates = RECIPES.filter((recipe) => recipe.item === item);
    const selectedRecipe = recipeById.get(selectedRecipeId);
    const recipe = (item === targetItem && selectedRecipe?.item === item ? selectedRecipe : null) || candidates[0];
    if (!recipe) throw new Error(`Нет рецепта для продукта «${itemLabel(item)}». Добавь его в app.js.`);

    const machineEquivalent = requiredRate / recipe.output;
    const current = machines.get(recipe.id);
    if (current) {
      current.machineEquivalent += machineEquivalent;
      current.outputRate += requiredRate;
      current.depth = Math.max(current.depth, depth);
    } else {
      machines.set(recipe.id, {
        recipe,
        machineEquivalent,
        outputRate: requiredRate,
        depth,
        order: order++
      });
    }

    path.push(item);
    for (const input of recipe.inputs) {
      expand(input.item, requiredRate * input.rate / recipe.output, depth + 1);
    }
    path.pop();
  }

  expand(targetItem, targetRate, 0);

  const machineRows = [...machines.values()].map((entry) => {
    const meta = MACHINE_META[entry.recipe.machine] || { label: entry.recipe.machine, icon: "▣", power: 0 };
    const buildings = Math.max(1, Math.ceil(entry.machineEquivalent - 1e-9));
    const clock = entry.machineEquivalent / buildings;
    // Satisfactory's approximate underclock power curve: power scales as clock^1.321928.
    const power = meta.power * buildings * Math.pow(clock, 1.321928);
    return { ...entry, meta, buildings, clock, power };
  }).sort((a, b) => b.depth - a.depth || a.order - b.order);

  const totalBuildings = machineRows.reduce((sum, row) => sum + row.buildings, 0);
  const totalMachineEquivalent = machineRows.reduce((sum, row) => sum + row.machineEquivalent, 0);
  const totalPower = machineRows.reduce((sum, row) => sum + row.power, 0);

  return {
    targetItem,
    targetRate,
    machineRows,
    rawRows: [...raw.entries()].map(([item, rate]) => ({ item, rate })).sort((a, b) => b.rate - a.rate),
    totalBuildings,
    totalMachineEquivalent,
    totalPower
  };
}

function renderPlan(plan) {
  currentPlan = plan;
  $("#copy-plan-button").disabled = false;
  $("#result-product").textContent = itemLabel(plan.targetItem);
  $("#result-rate").textContent = formatNumber(plan.targetRate);
  $("#metric-machines").textContent = formatNumber(plan.totalBuildings);
  $("#metric-machines-note").textContent = `${formatNumber(plan.totalMachineEquivalent, true)} экв. машин`;
  $("#metric-power").textContent = `${formatNumber(plan.totalPower, true)}`;
  $("#metric-resources").textContent = formatNumber(plan.rawRows.length);
  $("#result-status").innerHTML = "<i></i> ПЛАН РАССЧИТАН";
  $("#result-footer-text").textContent = `Цепочка рассчитана для выпуска ${formatNumber(plan.targetRate)} ед. / мин.`;
  $("#machine-count-badge").textContent = `${formatNumber(plan.totalBuildings)} МАШИН`;

  const machinesList = $("#machines-list");
  machinesList.classList.remove("empty-state");
  machinesList.replaceChildren();
  for (const row of plan.machineRows) {
    const node = document.createElement("div");
    node.className = "machine-row";
    node.innerHTML = `
      <div class="machine-name">
        <span class="machine-glyph">${row.meta.icon}</span>
        <div><strong>${row.meta.label}</strong><small>${itemLabel(row.recipe.item)} · ${formatNumber(row.outputRate)}/мин</small></div>
      </div>
      <div class="machine-data"><strong>${formatNumber(row.buildings)}</strong><small>зданий</small></div>
      <div class="machine-data"><strong>${formatNumber(row.clock * 100)}%</strong><small>скорость</small></div>
      <div class="machine-data power-value"><strong>${formatNumber(row.power, true)}</strong><small>МВт</small></div>`;
    machinesList.append(node);
  }

  const resourcesList = $("#resources-list");
  resourcesList.classList.remove("empty-state");
  resourcesList.replaceChildren();
  for (const row of plan.rawRows) {
    const meta = RAW_ITEMS[row.item];
    const node = document.createElement("div");
    node.className = "resource-row";
    node.innerHTML = `
      <span class="resource-glyph">${meta.icon}</span>
      <div><strong>${meta.label}</strong><small>${row.item.toUpperCase()}</small></div>
      <div class="resource-rate">${formatNumber(row.rate)} <span>/ мин</span></div>`;
    resourcesList.append(node);
  }

  const flowList = $("#flow-list");
  flowList.classList.remove("empty-flow");
  flowList.replaceChildren();
  const flowNodes = [
    ...plan.rawRows.map((row) => ({ type: "raw", item: row.item, rate: row.rate })),
    ...plan.machineRows.map((row) => ({ type: "machine", item: row.recipe.item, rate: row.outputRate, machine: row.meta.label, count: row.machineEquivalent }))
  ];
  flowNodes.forEach((entry, index) => {
    if (index > 0) {
      const arrow = document.createElement("span");
      arrow.className = "flow-arrow";
      arrow.textContent = "→";
      flowList.append(arrow);
    }
    const node = document.createElement("div");
    node.className = "flow-node";
    if (entry.type === "raw") {
      node.innerHTML = `<span>${RAW_ITEMS[entry.item].icon}</span><div><strong>${itemLabel(entry.item)}</strong><small>${formatNumber(entry.rate)} / мин · сырьё</small></div>`;
    } else {
      node.innerHTML = `<span>${ITEM_ICONS[entry.item] || "▰"}</span><div><strong>${itemLabel(entry.item)}</strong><small>${entry.machine} · ${formatNumber(entry.count, true)} экв.</small></div>`;
    }
    flowList.append(node);
  });

  savePreference("ficsit-product", plan.targetItem);
  savePreference("ficsit-rate", String(plan.targetRate));
  savePreference("ficsit-recipe", recipeSelect.value);
}

function runCalculation({ silent = false } = {}) {
  currentPlan = null;
  $("#copy-plan-button").disabled = true;
  const targetItem = productSelect.value;
  const targetRate = parseRate(rateInput.value);
  if (!Number.isFinite(targetRate) || targetRate <= 0 || targetRate > 10000) {
    const message = "Введи значение от 0,1 до 10 000 ед. в минуту.";
    rateInput.setCustomValidity(message);
    $("#result-status").innerHTML = "<i></i> ПРОВЕРЬ ВЫПУСК";
    $("#result-footer-text").textContent = message;
    if (!silent) rateInput.reportValidity();
    return;
  }
  rateInput.setCustomValidity("");
  try {
    const plan = calculatePlan(targetItem, targetRate, recipeSelect.value);
    renderPlan(plan);
  } catch (error) {
    $("#result-status").innerHTML = "<i></i> НУЖНА ПРОВЕРКА РЕЦЕПТА";
    $("#result-footer-text").textContent = error.message;
  }
}

function showView(name) {
  const planner = name === "planner";
  $("#view-planner").hidden = !planner;
  $("#view-pilot").hidden = planner;
  document.querySelectorAll(".nav-item").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#current-section").textContent = planner ? "ПЛАН ПРОИЗВОДСТВА" : "ИГРОВОЙ АВТОПИЛОТ";
  try { history.replaceState(null, "", planner ? "#planner" : "#pilot"); } catch { location.hash = planner ? "planner" : "pilot"; }
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(lastToastTimer);
  lastToastTimer = setTimeout(() => toast.classList.remove("show"), 1900);
}

async function copyText(text, message = "Команда скопирована") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  showToast(message);
}

function buildPilotMission(plan) {
  const machineLines = plan.machineRows.map((row) =>
    `- ${row.meta.label}: ${row.buildings} шт. для «${itemLabel(row.recipe.item)}» (${formatNumber(row.outputRate)} ед./мин, около ${formatNumber(row.clock * 100)}% скорости).`
  );
  const rawLines = plan.rawRows.map((row) =>
    `- ${itemLabel(row.item)}: ${formatNumber(row.rate)} ед./мин.`
  );
  return [
    `На существующем сохранении Satisfactory безопасно организуй производство «${itemLabel(plan.targetItem)}» с целью ${formatNumber(plan.targetRate)} ед./мин.`,
    "Сначала осмотри текущую базу. Используй существующие линии, если они подходят; не разбирай и не перезаписывай постройки.",
    "Ориентировочный машинный план (число зданий можно уточнить по доступному месту и ресурсам):",
    ...machineLines,
    "Сырьевой спрос в минуту:",
    ...rawLines,
    "Не расходуй редкие ресурсы и не делай опасных действий без необходимости. Если нужной технологии/ресурсов нет или следующий шаг неочевиден — остановись и попроси игрока вмешаться."
  ].join("\n");
}

populateProducts();
filterProductOptions();
const savedRate = Number(readPreference("ficsit-rate"));
if (Number.isFinite(savedRate) && savedRate > 0 && savedRate <= 10000) rateInput.value = String(savedRate);
populateRecipes(readPreference("ficsit-recipe"));
runCalculation();

productSearch.addEventListener("input", filterProductOptions);
productSelect.addEventListener("change", () => {
  productSearch.value = "";
  filterProductOptions();
  populateRecipes();
  runCalculation();
});
recipeSelect.addEventListener("change", runCalculation);
rateInput.addEventListener("input", () => runCalculation({ silent: true }));
rateInput.addEventListener("change", () => runCalculation());
$("#calculate-button").addEventListener("click", runCalculation);
$("#rate-down").addEventListener("click", () => {
  const current = parseRate(rateInput.value);
  rateInput.value = String(Math.max(0.1, (Number.isFinite(current) ? current : 0) - 0.5));
  runCalculation();
});
$("#rate-up").addEventListener("click", () => {
  const current = parseRate(rateInput.value);
  rateInput.value = String(Math.min(10000, (Number.isFinite(current) ? current : 0) + 0.5));
  runCalculation();
});
document.querySelectorAll(".rate-chip").forEach((button) => button.addEventListener("click", () => {
  rateInput.value = button.dataset.rate;
  runCalculation();
}));
document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
document.querySelectorAll(".copy-button").forEach((button) => button.addEventListener("click", () => copyText(button.dataset.copy)));
$("#copy-plan-button").addEventListener("click", () => {
  if (currentPlan) copyText(buildPilotMission(currentPlan), "План скопирован — вставь в pilot/goal.txt");
});
if (location.hash === "#pilot") showView("pilot");
