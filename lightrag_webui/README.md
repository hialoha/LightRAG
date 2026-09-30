# LightRAG WebUI

LightRAG WebUI is a React-based web interface for interacting with the LightRAG system. It provides a user-friendly interface for querying, managing, and exploring LightRAG's functionalities.

## Installation

1. **Install Bun:**

    If you haven't already installed Bun, follow the official documentation: [https://bun.sh/docs/installation](https://bun.sh/docs/installation)

2. **Install Dependencies:**

    In the `lightrag_webui` directory, run the following command to install project dependencies:

    ```bash
    bun install --frozen-lockfile
    ```

3. **Build the Project:**

    Run the following command to build the project:

    ```bash
    bun run build
    ```

    This command will bundle the project and output the built files to the `lightrag/api/webui` directory.

## Development

Keep `VITE_BACKEND_URL` empty in `.env.local` for a same-origin deployment. The
browser then uses the current website's protocol, hostname and port. Set an
absolute backend URL only when the frontend and backend are deployed separately.
Bun can load `.env.local` into the process environment before Vite starts, so an
old value there can override mode-specific Vite configuration.

During development, Vite proxies API and authentication requests to
`VITE_BACKEND_PROXY_TARGET` (default: `http://localhost:9621`). This address is used
by the development server, not by the remote browser. `python -m lightrag.run`
sets the proxy target from the workspace configuration.

After changing a production backend setting, run `bun run build` and refresh the
browser. Restarting only the Python backend does not rebuild browser assets.

- **Start the Development Server:**

  If you want to run the WebUI in development mode, use the following command:

  ```bash
  bun run dev
  ```

## Script Commands

The following are some commonly used script commands defined in `package.json`:

- `bun install`: Installs project dependencies.
- `bun run dev`: Starts the development server.
- `bun run build`: Builds the project.
- `bun run lint`: Runs the linter.
- `bun test`: Runs the URL, authentication and login form regression tests.
- `bun run test:vitest`: Runs the same specs with Vitest.
