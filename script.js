// Function to fetch menu data from the backend
const fetchMenuData = async () => {
  try {
    const response = await fetch('http://localhost:5000/menu');
    if (!response.ok) {
      throw new Error('Failed to fetch menu data');
    }
    const menuData = await response.json();
    return menuData;
  } catch (error) {
    console.error('Error fetching menu data:', error);
    return null; // Handle errors gracefully
  }
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

// Initialize the page by fetching and populating the menu data
const initializeMenu = async () => {
  const menuData = await fetchMenuData();
  if (menuData) {
    fillTable("week1", menuData["1"]); // Week 1 data
    fillTable("week2", menuData["2"]); // Week 2 data
  } else {
    console.error('Failed to initialize menu data');
  }
};

// Call initializeMenu on page load
initializeMenu();

