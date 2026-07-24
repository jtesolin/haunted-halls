This is the public-facing Next.js Backend-for-Frontend for Haunted Halls.

## Getting Started

1. Install dependencies:

```bash
npm install
```

2. Copy environment defaults:

```bash
cp .env.example .env
```

3. Generate a strong `NEXTAUTH_SECRET`:

```bash
openssl rand -base64 32
```

4. Start the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Google Sign-In Setup

1. In Google Cloud Console, create or select a project.
2. Configure the OAuth consent screen (External or Internal, based on your org policy).
3. Create credentials of type OAuth 2.0 Client ID, selecting Web application.
4. Configure OAuth client values:

- Authorized JavaScript origin (local): `http://localhost:3000`
- Authorized redirect URI (local): `http://localhost:3000/api/auth/callback/google`
- Production redirect URI pattern: `https://<your-domain>/api/auth/callback/google`

5. Set these variables in `.env`:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `NEXTAUTH_SECRET`
- `NEXTAUTH_URL` (for local default: `http://localhost:3000`)

If you run the app on a different port, update `NEXTAUTH_URL` and register the matching origin and redirect URI in Google Cloud.

## Auth Notes

- Authentication uses Auth.js/NextAuth with Google OpenID Connect scopes: `openid email profile`.
- Session strategy is stateless JWT managed by NextAuth cookies.
- No Google tokens are stored in browser storage.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## License

The source code in this repository is licensed under the MIT License.

Game content, lore, prompts, characters, and narrative text are not included
under the MIT License unless explicitly stated otherwise.
