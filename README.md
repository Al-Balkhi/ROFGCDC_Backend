# Route Optimization for Garbage Collection in Damascus City (ROFGCDC)

**A specialized Route Optimization System designed for garbage collection in Damascus City.**

This backend system leverages advanced Vehicle Routing Problem (VRP) algorithms (Google OR-Tools) and geospatial data (OSRM) to automate the generation of optimal collection tours. By analyzing bin locations, vehicle capacities, and disposal sites, the system ensures resources are utilized effectively to reduce operational costs and improve collection efficiency.

## ✨ Features

- **Intelligent Route Optimization**: Solves the Vehicle Routing Problem (VRP) using Google OR-Tools to generate the most efficient paths based on real-world road networks.
- **Role-Based Access Control (RBAC)**: Distinct workflows for **Admins** (system oversight), **Planners** (scenario creation), and **Drivers** (route execution).
- **Secure Authentication**: Implements JWT authentication via HttpOnly cookies and OTP-based initial setup/password recovery.
- **Asset Management & Geofencing**: Manages municipalities, landfills, bins, and vehicles, with strict coordinate validation to ensure all assets are located within Damascus city bounds.
- **Distance Matrix Calculation**: Integrated with a local OSRM (Open Source Routing Machine) instance for accurate travel time and distance calculations.

## 🛠 Tech Stack

- **Language**: Python 3.10+
- **Framework**: Django 5.2, Django Rest Framework
- **Database**: PostgreSQL
- **Optimization**: Google OR-Tools, NumPy, Pandas
- **Routing**: OSRM (Open Source Routing Machine)
- **Infrastructure**: Docker (for OSRM service)

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL
- Docker (required for the OSRM routing engine)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/ROFGCDC_Backend.git
cd ROFGCDC_Backend
```

2. **Set up the Virtual Environment**
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

4. **Environment Configuration**

Create a `.env` file in the root directory:

```env
# Core
SECRET_KEY=your_secret_key
DEBUG=True
CORS_ALLOWED_ORIGINS=http://localhost:5173

# Database
DB_NAME=ROFGCIDC
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432

# Email (Gmail SMTP)
EMAIL_HOST_USER=example@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# OSRM Service
OSRM_BASE_URL=http://localhost:5000
```

5. **Initialize Database**
```bash
python manage.py migrate
python manage.py createsuperuser
```

6. **Start OSRM Service (Critical)**
```bash
docker run -t -i -p 5000:5000 -v "${PWD}:/data" osrm/osrm-backend   osrm-routed --algorithm mld /data/syria-latest.osrm
```

7. **Run the Server**
```bash
python manage.py runserver
```

## 📖 Detailed Usage

### The Optimization Workflow

1. **Define Assets**: Admin users populate the database with `Municipality`, `Landfill`, `Vehicle`, and `Bin` entries.
2. **Create Scenario**: A Planner creates a `Scenario` for a specific collection date, assigning a vehicle and selecting a set of active bins.
3. **Solve**: Trigger the solver endpoint. The backend:
   - Fetches the distance matrix from OSRM.
   - Applies constraints (vehicle capacity, start/end locations).
   - Calculates the optimal path using `pywrapcp` (OR-Tools).
4. **Result**: A `RouteSolution` is generated containing the sequence of stops and total distance.

### Example: Solving a Scenario via API

**Endpoint:** `POST /api/scenarios/{id}/solve/`

**Response:**
```json
{
  "total_distance": 15.4,
  "routes": [
    {
      "vehicle": "Truck A",
      "vehicle_id": 1,
      "stops": [5, 12, 8, 3]
    }
  ],
  "solution_id": 42
}
```

## 🔌 API Reference

### Authentication (`/api/auth/`)

- `POST /login/`: Returns user details and sets HttpOnly `access` and `refresh` cookies.
- `POST /initial-setup/request-otp/`: Requests an OTP for new accounts created without passwords.
- `POST /password/reset/request/`: Initiates password recovery flow.

### Optimization (`/api/`)

- `GET /bins/available/`: Lists bins not currently assigned to other active scenarios for the day.
- `POST /scenarios/`: Create a new planning scenario.
- `POST /scenarios/{id}/solve/`: Trigger the VRP solver algorithm.
- `GET /solutions/`: Retrieve calculated route history.

## 🤝 Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/NewAlgorithm`).
3. Commit your changes (`git commit -m 'Add new capacity constraint'`).
4. Push to the branch (`git push origin feature/NewAlgorithm`).
5. Open a Pull Request.

**Code Style**: Ensure all new models utilize the `DamascusLocationMixin` or validators to maintain geospatial integrity.

## 📄 License & Credits

- **License**: MIT License (Assumed, please verify).
- **Credits**:
  - Routing data provided by OpenStreetMap
  - Optimization engine powered by Google OR-Tools
