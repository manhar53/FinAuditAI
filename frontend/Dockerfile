FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-fund --no-audit
COPY index.html vite.config.js ./
COPY src ./src
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
