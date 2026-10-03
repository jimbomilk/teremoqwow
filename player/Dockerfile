FROM node:20-alpine AS dev

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]

# ── Production build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json ./
RUN npm install --production=false
COPY . .
RUN npm run build

FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/index.html /usr/share/nginx/html/
EXPOSE 80
