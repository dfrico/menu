const data = {
  week1: {
    Monday: { Lunch: "Pasta", Dinner: "Salad" },
    Tuesday: { Lunch: "Pizza", Dinner: "Soup" },
    Wednesday: { Lunch: "Burger", Dinner: "Fries" },
    Thursday: { Lunch: "Rice", Dinner: "Chicken" },
    Friday: { Lunch: "Sandwich", Dinner: "Steak" },
    Saturday: { Lunch: "Tacos", Dinner: "Fish" },
    Sunday: { Lunch: "Pancakes", Dinner: "Omelette" },
  },
  week2: {
    Monday: { Lunch: "Lasagna", Dinner: "Veggies" },
    Tuesday: { Lunch: "Wraps", Dinner: "Noodles" },
    Wednesday: { Lunch: "Sushi", Dinner: "Tempura" },
    Thursday: { Lunch: "BBQ", Dinner: "Corn" },
    Friday: { Lunch: "Curry", Dinner: "Bread" },
    Saturday: { Lunch: "Soup", Dinner: "Salmon" },
    Sunday: { Lunch: "Toast", Dinner: "Jam" },
  },
};

const fillTable = (weekId, weekData) => {
  const tbody = document.querySelector(`#${weekId} tbody`);

  // Create rows for Lunch and Dinner
  ["Lunch", "Dinner"].forEach(meal => {
    const row = document.createElement("tr");
    const mealCell = document.createElement("td");
    mealCell.textContent = meal; // Add "Lunch" or "Dinner" as the first cell
    row.appendChild(mealCell);

    // Add data for each day of the week
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].forEach(day => {
      const mealDataCell = document.createElement("td");
      mealDataCell.textContent = weekData[day][meal];
      mealDataCell.setAttribute("draggable", "true");

      // Add drag-and-drop functionality
      mealDataCell.addEventListener("dragstart", e => {
        mealDataCell.classList.add("dragging");
        e.dataTransfer.setData("text/plain", e.target.textContent);
      });

      mealDataCell.addEventListener("dragover", e => {
        e.preventDefault();
      });

      mealDataCell.addEventListener("drop", e => {
        e.preventDefault();
        const draggingCell = document.querySelector(".dragging");
        const droppedText = e.dataTransfer.getData("text/plain");
        draggingCell.textContent = e.target.textContent;
        e.target.textContent = droppedText;
        draggingCell.classList.remove("dragging");
      });

      mealDataCell.addEventListener("dragend", () => {
        mealDataCell.classList.remove("dragging");
      });

      row.appendChild(mealDataCell);
    });

    tbody.appendChild(row);
  });
};

// Populate tables with updated structure
fillTable("week1", data.week1);
fillTable("week2", data.week2);

