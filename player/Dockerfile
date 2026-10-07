FROM node:20-alpine AS dev

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]

# ── Production build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS build

# Build-time vars que Vite sustituye en el bundle
ARG VITE_MOQ_RELAY_URL=https://wow.teremoq.com:4443/anon
ARG VITE_RELAY_BROADCAST=anon/live1
ARG VITE_MOQ_CERT_HASH=
ENV VITE_MOQ_RELAY_URL=$VITE_MOQ_RELAY_URL
ENV VITE_RELAY_BROADCAST=$VITE_RELAY_BROADCAST
ENV VITE_MOQ_CERT_HASH=$VITE_MOQ_CERT_HASH

WORKDIR /app
COPY package.json ./
RUN npm install --production=false
COPY . .
RUN npm run build

FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
